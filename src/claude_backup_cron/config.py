"""TOML configuration loader.

Layout (example)
----------------

.. code-block:: toml

   [global]
   state_dir = "~/.local/state/claude-backup-cron"
   alert_webhook = "https://discord.com/api/webhooks/..."

   [[sources]]
   id = "claude-memory"
   path = "~/.claude/projects/-home-USER/memory"
   exclude = [".git/*", "*.swp"]

   [[destinations]]
   id = "private-github"
   kind = "git"
   remote = "git@github.com:me/claude-memory-backup.git"
   branch = "main"
   encrypt_to = "age1abc..."

   [[destinations]]
   id = "s3-offsite"
   kind = "s3"
   bucket = "my-backup-bucket"
   prefix = "claude-memory/"
   encrypt_to = "age1abc..."

Resolution order
----------------

1. ``$CLAUDE_BACKUP_CRON_CONFIG`` (explicit path) if set.
2. ``$XDG_CONFIG_HOME/claude-backup-cron/config.toml``.
3. ``~/.config/claude-backup-cron/config.toml``.

An empty / missing config is a hard error — unlike a linter, we have
nothing sensible to do without at least one source and one destination.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_backup_cron.errors import ConfigError

if sys.version_info >= (3, 11):
    import tomllib  # pragma: no cover — stdlib since 3.11
else:  # pragma: no cover — only exercised on the 3.10 CI matrix cell
    import tomli as tomllib  # type: ignore[no-redef, import-not-found, unused-ignore]


_VALID_DEST_KINDS = frozenset({"git", "s3", "local"})


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """A single directory (or file) to back up."""

    id: str
    path: Path
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DestinationSpec:
    """A single destination — see ``kind`` for which backend is used.

    ``encrypt_to`` is an age recipient string. If set, the tarball is
    encrypted with ``age`` before upload. We refuse to fall back to
    plaintext on encryption failure — see :class:`EncryptionError`.
    """

    id: str
    kind: str
    encrypt_to: str | None = None
    # kind-specific:
    remote: str | None = None
    branch: str | None = None
    bucket: str | None = None
    prefix: str | None = None
    s3_endpoint: str | None = None
    path: Path | None = None
    retain: int | None = None


@dataclass(frozen=True, slots=True)
class GlobalSpec:
    """Top-level config — the ``[global]`` table."""

    state_dir: Path
    alert_webhook: str | None = None


@dataclass(frozen=True, slots=True)
class Config:
    """Loaded + validated top-level config."""

    global_: GlobalSpec
    sources: tuple[SourceSpec, ...]
    destinations: tuple[DestinationSpec, ...]
    source_path: Path

    extra_keys: tuple[str, ...] = field(default_factory=tuple)


def _expand(p: str | Path) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(str(p))))


def _default_state_dir() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "claude-backup-cron"
    return Path.home() / ".local" / "state" / "claude-backup-cron"


def _resolve_config_path() -> Path | None:
    override = os.environ.get("CLAUDE_BACKUP_CRON_CONFIG")
    if override:
        return _expand(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    candidates: list[Path] = []
    if xdg:
        candidates.append(Path(xdg) / "claude-backup-cron" / "config.toml")
    candidates.append(Path.home() / ".config" / "claude-backup-cron" / "config.toml")
    for c in candidates:
        if c.is_file():
            return c
    return None


def _parse_source(entry: dict[str, Any], index: int) -> SourceSpec:
    try:
        sid = str(entry["id"])
        raw_path = entry["path"]
    except KeyError as exc:
        raise ConfigError(f"sources[{index}] is missing required key {exc.args[0]!r}") from exc
    excludes_raw = entry.get("exclude", [])
    if not isinstance(excludes_raw, list) or not all(isinstance(x, str) for x in excludes_raw):
        raise ConfigError(f"sources[{index}].exclude must be a list of strings")
    return SourceSpec(
        id=sid,
        path=_expand(raw_path),
        exclude=tuple(excludes_raw),
    )


def _parse_destination(entry: dict[str, Any], index: int) -> DestinationSpec:
    try:
        did = str(entry["id"])
        kind = str(entry["kind"])
    except KeyError as exc:
        raise ConfigError(f"destinations[{index}] is missing required key {exc.args[0]!r}") from exc
    if kind not in _VALID_DEST_KINDS:
        raise ConfigError(
            f"destinations[{index}].kind = {kind!r} is not one of {sorted(_VALID_DEST_KINDS)}"
        )
    encrypt_to = entry.get("encrypt_to")
    if encrypt_to is not None and not isinstance(encrypt_to, str):
        raise ConfigError(f"destinations[{index}].encrypt_to must be a string")

    raw_path = entry.get("path")
    dest_path = _expand(raw_path) if raw_path is not None else None
    retain = entry.get("retain")
    # ``isinstance(True, int)`` is True in Python — reject booleans explicitly
    # so ``retain = true`` doesn't silently become 1.
    if retain is not None and (
        not isinstance(retain, int) or isinstance(retain, bool) or retain < 1
    ):
        raise ConfigError(f"destinations[{index}].retain must be a positive int")

    spec = DestinationSpec(
        id=did,
        kind=kind,
        encrypt_to=encrypt_to,
        remote=entry.get("remote"),
        branch=entry.get("branch"),
        bucket=entry.get("bucket"),
        prefix=entry.get("prefix"),
        s3_endpoint=entry.get("s3_endpoint"),
        path=dest_path,
        retain=retain,
    )

    # Kind-specific required-field validation.
    if kind == "git" and not spec.remote:
        raise ConfigError(f"destinations[{index}] (git): 'remote' is required")
    if kind == "s3" and not spec.bucket:
        raise ConfigError(f"destinations[{index}] (s3): 'bucket' is required")
    if kind == "local" and spec.path is None:
        raise ConfigError(f"destinations[{index}] (local): 'path' is required")

    return spec


def load(path: Path | None = None) -> Config:
    """Load and validate config. See module docstring for resolution order."""
    resolved = path if path is not None else _resolve_config_path()
    if resolved is None:
        raise ConfigError(
            "No config found. Set $CLAUDE_BACKUP_CRON_CONFIG or create "
            "~/.config/claude-backup-cron/config.toml (see examples/config.toml)."
        )
    if not resolved.is_file():
        raise ConfigError(f"Config file not found: {resolved}")

    try:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{resolved}: malformed TOML: {exc}") from exc

    global_block = data.get("global", {})
    if not isinstance(global_block, dict):
        raise ConfigError("[global] must be a table")
    raw_state_dir = global_block.get("state_dir")
    state_dir = _expand(raw_state_dir) if raw_state_dir else _default_state_dir()
    alert_webhook = global_block.get("alert_webhook")
    if alert_webhook is not None and not isinstance(alert_webhook, str):
        raise ConfigError("[global].alert_webhook must be a string URL")

    sources_raw = data.get("sources", [])
    if not isinstance(sources_raw, list) or not sources_raw:
        raise ConfigError("At least one [[sources]] table is required")
    sources = tuple(_parse_source(s, i) for i, s in enumerate(sources_raw))

    # Duplicate-ID detection — downstream code keys state files on id.
    src_ids = [s.id for s in sources]
    if len(src_ids) != len(set(src_ids)):
        raise ConfigError("Duplicate source id(s): " + ", ".join(sorted(set(src_ids))))

    destinations_raw = data.get("destinations", [])
    if not isinstance(destinations_raw, list) or not destinations_raw:
        raise ConfigError("At least one [[destinations]] table is required")
    destinations = tuple(_parse_destination(d, i) for i, d in enumerate(destinations_raw))
    dest_ids = [d.id for d in destinations]
    if len(dest_ids) != len(set(dest_ids)):
        raise ConfigError("Duplicate destination id(s): " + ", ".join(sorted(set(dest_ids))))

    known_top = {"global", "sources", "destinations"}
    extras = tuple(sorted(k for k in data if k not in known_top))

    return Config(
        global_=GlobalSpec(state_dir=state_dir, alert_webhook=alert_webhook),
        sources=sources,
        destinations=destinations,
        source_path=resolved,
        extra_keys=extras,
    )
