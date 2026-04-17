"""Config loading + validation. No I/O beyond tmp_path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_backup_cron.config import load
from claude_backup_cron.errors import ConfigError

_MIN = """
[[sources]]
id = "src1"
path = "~/data"

[[destinations]]
id = "dst1"
kind = "local"
path = "/tmp/backup"
"""


def _write(tmp_path: Path, body: str, name: str = "config.toml") -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_minimal_config(tmp_path: Path) -> None:
    cfg = load(_write(tmp_path, _MIN))
    assert len(cfg.sources) == 1
    assert cfg.sources[0].id == "src1"
    assert cfg.destinations[0].kind == "local"
    assert cfg.global_.alert_webhook is None


def test_expanduser_is_applied(tmp_path: Path) -> None:
    cfg = load(_write(tmp_path, _MIN))
    assert not str(cfg.sources[0].path).startswith("~")
    assert cfg.sources[0].path.is_absolute()


def test_explicit_state_dir_is_honoured(tmp_path: Path) -> None:
    body = _MIN + '\n[global]\nstate_dir = "/var/tmp/mystate"\n'
    cfg = load(_write(tmp_path, body))
    # Path comparison (not string): Path normalises separators on Windows.
    assert cfg.global_.state_dir == Path("/var/tmp/mystate")


def test_alert_webhook_roundtrips(tmp_path: Path) -> None:
    body = _MIN + '\n[global]\nalert_webhook = "https://example.invalid/hook"\n'
    cfg = load(_write(tmp_path, body))
    assert cfg.global_.alert_webhook == "https://example.invalid/hook"


def test_empty_sources_rejected(tmp_path: Path) -> None:
    body = """
[[destinations]]
id = "dst1"
kind = "local"
path = "/tmp/backup"
"""
    with pytest.raises(ConfigError, match="sources"):
        load(_write(tmp_path, body))


def test_empty_destinations_rejected(tmp_path: Path) -> None:
    body = """
[[sources]]
id = "src1"
path = "~/data"
"""
    with pytest.raises(ConfigError, match="destinations"):
        load(_write(tmp_path, body))


def test_unknown_dest_kind_rejected(tmp_path: Path) -> None:
    body = """
[[sources]]
id = "s"
path = "~/data"

[[destinations]]
id = "d"
kind = "magic"
"""
    with pytest.raises(ConfigError, match="kind"):
        load(_write(tmp_path, body))


def test_git_dest_requires_remote(tmp_path: Path) -> None:
    body = """
[[sources]]
id = "s"
path = "~/data"

[[destinations]]
id = "d"
kind = "git"
"""
    with pytest.raises(ConfigError, match="remote"):
        load(_write(tmp_path, body))


def test_s3_dest_requires_bucket(tmp_path: Path) -> None:
    body = """
[[sources]]
id = "s"
path = "~/data"

[[destinations]]
id = "d"
kind = "s3"
"""
    with pytest.raises(ConfigError, match="bucket"):
        load(_write(tmp_path, body))


def test_local_dest_requires_path(tmp_path: Path) -> None:
    body = """
[[sources]]
id = "s"
path = "~/data"

[[destinations]]
id = "d"
kind = "local"
"""
    with pytest.raises(ConfigError, match="path"):
        load(_write(tmp_path, body))


def test_duplicate_source_ids_rejected(tmp_path: Path) -> None:
    body = """
[[sources]]
id = "same"
path = "~/a"

[[sources]]
id = "same"
path = "~/b"

[[destinations]]
id = "d"
kind = "local"
path = "/tmp/x"
"""
    with pytest.raises(ConfigError, match="Duplicate source"):
        load(_write(tmp_path, body))


def test_malformed_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="malformed"):
        load(_write(tmp_path, "this is = = not toml"))


def test_env_override(monkeypatch: Any, tmp_path: Path) -> None:
    p = _write(tmp_path, _MIN)
    monkeypatch.setenv("CLAUDE_BACKUP_CRON_CONFIG", str(p))
    cfg = load()
    assert cfg.source_path == p


def test_no_config_anywhere(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.delenv("CLAUDE_BACKUP_CRON_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    with pytest.raises(ConfigError, match="No config found"):
        load()


def test_retain_must_be_positive(tmp_path: Path) -> None:
    body = """
[[sources]]
id = "s"
path = "~/data"

[[destinations]]
id = "d"
kind = "local"
path = "/tmp/x"
retain = 0
"""
    with pytest.raises(ConfigError, match="retain"):
        load(_write(tmp_path, body))


def test_extra_keys_are_surfaced(tmp_path: Path) -> None:
    body = _MIN + '\n[experimental]\nfoo = "bar"\n'
    cfg = load(_write(tmp_path, body))
    assert cfg.extra_keys == ("experimental",)
