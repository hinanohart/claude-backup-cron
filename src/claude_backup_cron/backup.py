"""Orchestration: package every source, encrypt if asked, dispatch to
every destination, summarise.

Kept deliberately linear — the loop is short enough to read top-to-bottom.
Per-destination failures are collected rather than raised so one broken
S3 bucket doesn't block the git push that follows.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from claude_backup_cron import alerting, destinations, encryption, sources
from claude_backup_cron.errors import BackupError, DestinationError, EncryptionError, SourceError

if TYPE_CHECKING:
    from claude_backup_cron.config import Config, DestinationSpec

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StepResult:
    """Outcome of uploading one (source, destination) pair."""

    source_id: str
    destination_id: str
    ok: bool
    message: str


@dataclass(frozen=True, slots=True)
class RunReport:
    """Summary of a whole backup run."""

    dry_run: bool
    results: tuple[StepResult, ...]

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def failed(self) -> tuple[StepResult, ...]:
        return tuple(r for r in self.results if not r.ok)


def run(config: Config, *, dry_run: bool = False) -> RunReport:
    """Execute the backup plan described by ``config``.

    With ``dry_run=True`` we package sources (so change-detection and
    error reporting still work) but skip encryption and all destination
    dispatch. A preview, in other words.
    """
    state_dir = config.global_.state_dir
    _ensure_private_dir(state_dir)

    pack_dir = state_dir / "packages"
    work_dir = state_dir / "work"
    _ensure_private_dir(pack_dir)
    _ensure_private_dir(work_dir)

    results: list[StepResult] = []

    # Phase 1: package every source up-front. If any source is broken we
    # want to know early, before burning a single upload on a partial run.
    artefacts: list[sources.Artefact] = []
    for spec in config.sources:
        try:
            artefact = sources.package(spec, pack_dir)
        except SourceError as exc:
            _LOG.error("source %s: %s", spec.id, exc)
            for dest in config.destinations:
                results.append(
                    StepResult(
                        source_id=spec.id,
                        destination_id=dest.id,
                        ok=False,
                        message=f"packaging failed: {exc}",
                    )
                )
            continue
        artefacts.append(artefact)

    # Phase 2: for each (source, destination), encrypt if needed then dispatch.
    for artefact in artefacts:
        encrypted_artefacts: list[Path] = []
        for dest in config.destinations:
            if dry_run:
                results.append(
                    StepResult(
                        source_id=artefact.source_id,
                        destination_id=dest.id,
                        ok=True,
                        message=f"dry-run: would upload {artefact.path.name}",
                    )
                )
                continue
            try:
                to_upload = _maybe_encrypt(artefact.path, dest, work_dir)
                if dest.encrypt_to is not None:
                    encrypted_artefacts.append(to_upload)
                up = destinations.Upload(
                    source_id=artefact.source_id,
                    digest=artefact.digest,
                    artefact=to_upload,
                    encrypted=dest.encrypt_to is not None,
                )
                msg = _dispatch(dest, up, work_dir)
            except (EncryptionError, DestinationError) as exc:
                _LOG.error("dest %s / source %s: %s", dest.id, artefact.source_id, exc)
                results.append(
                    StepResult(
                        source_id=artefact.source_id,
                        destination_id=dest.id,
                        ok=False,
                        message=str(exc),
                    )
                )
                continue
            except BackupError as exc:
                _LOG.error(
                    "dest %s / source %s: unexpected backup error: %s",
                    dest.id,
                    artefact.source_id,
                    exc,
                )
                results.append(
                    StepResult(
                        source_id=artefact.source_id,
                        destination_id=dest.id,
                        ok=False,
                        message=str(exc),
                    )
                )
                continue
            results.append(
                StepResult(
                    source_id=artefact.source_id,
                    destination_id=dest.id,
                    ok=True,
                    message=msg,
                )
            )

        if not dry_run:
            # pack_dir is transient working space — scrub plaintext + encrypted
            # copies once every destination for this artefact has been dispatched.
            # The dest (repo/S3/local) is the durable store, not pack_dir.
            for enc in encrypted_artefacts:
                _safe_unlink(enc)
            _safe_unlink(artefact.path)

    report = RunReport(dry_run=dry_run, results=tuple(results))

    if not dry_run and report.failed and config.global_.alert_webhook:
        summary = "; ".join(f"{r.source_id}→{r.destination_id}: {r.message}" for r in report.failed)
        alerting.post(
            config.global_.alert_webhook,
            f"claude-backup-cron: {len(report.failed)} step(s) failed — {summary}",
        )

    return report


def _ensure_private_dir(path: Path) -> None:
    """Create ``path`` with mode 0700 (owner-only), enforcing on existing dirs too."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        # Best-effort: on Windows / NFS / FUSE some chmods silently noop.
        _LOG.debug("could not chmod 0700 on %s", path, exc_info=True)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        _LOG.debug("could not unlink %s", path, exc_info=True)


def _maybe_encrypt(
    src: Path,
    dest: DestinationSpec,
    work_dir: Path,
) -> Path:
    """If ``dest.encrypt_to`` is set, produce an age-encrypted copy."""
    if dest.encrypt_to is None:
        return src
    encrypted = work_dir / f"{src.name}.age"
    encryption.encrypt_file(src, encrypted, recipient=dest.encrypt_to)
    return encrypted


def _dispatch(
    dest: DestinationSpec,
    upload: destinations.Upload,
    work_dir: Path,
) -> str:
    kind = dest.kind
    if kind == "local":
        return destinations.dispatch_local(dest, upload)
    if kind == "git":
        return destinations.dispatch_git(dest, upload, work_root=work_dir)
    if kind == "s3":
        return destinations.dispatch_s3(dest, upload)
    raise DestinationError(f"unknown destination kind: {kind!r}")
