"""Destination backends: git, s3, local.

A destination takes an already-packaged (and possibly encrypted)
artefact file plus a small record of "what this artefact represents"
and uploads / stores it. Each backend is a thin wrapper around the
canonical tool (``git`` / ``aws`` / filesystem) — we don't reinvent
transport, we just orchestrate.

Each function returns a one-line status string (for logs/alerts) or
raises :class:`DestinationError` on failure. The backup runner catches
per-destination failures so one broken destination doesn't sabotage the
others.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from claude_backup_cron.errors import DestinationError

if TYPE_CHECKING:
    from claude_backup_cron.config import DestinationSpec

UTC = timezone.utc


@dataclass(frozen=True, slots=True)
class Upload:
    """What the runner hands to each destination for a single artefact."""

    source_id: str
    digest: str
    artefact: Path
    encrypted: bool


def _run(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke a child process with a fixed argv (no shell)."""
    try:
        return subprocess.run(  # noqa: S603 — fixed argv.
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DestinationError(f"{argv[0]} not found on PATH") from exc


# --------- local -------------------------------------------------------


def dispatch_local(dest: DestinationSpec, upload: Upload) -> str:
    """Copy the artefact into a local directory, optionally rotating."""
    if dest.path is None:  # defensive; config validation should have caught this
        raise DestinationError(f"local dest {dest.id!r}: missing 'path'")
    dest.path.mkdir(parents=True, exist_ok=True)
    target = dest.path / upload.artefact.name
    try:
        shutil.copy2(upload.artefact, target)
    except OSError as exc:
        raise DestinationError(f"local dest {dest.id!r}: copy failed: {exc}") from exc

    if dest.retain is not None:
        _rotate(dest.path, upload.source_id, dest.retain)

    return f"copied to {target}"


def _rotate(dir_: Path, source_id: str, keep: int) -> None:
    """Keep the ``keep`` most recent artefacts for a given source ID.

    Tolerant of concurrent deletion: if another process races us between
    ``iterdir()`` and ``stat()``, we just treat the vanished file as
    oldest-possible rather than crashing the whole backup.
    """

    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except FileNotFoundError:
            return float("-inf")

    try:
        entries = list(dir_.iterdir())
    except FileNotFoundError:
        return
    artefacts = sorted(
        (p for p in entries if p.is_file() and p.name.startswith(f"{source_id}-")),
        key=_mtime,
        reverse=True,
    )
    for stale in artefacts[keep:]:
        try:
            stale.unlink()
        except OSError:
            # Best-effort cleanup; a stuck file shouldn't fail the whole run.
            continue


# --------- git ---------------------------------------------------------


def _is_valid_git_repo(clone: Path) -> bool:
    """True iff ``clone`` is a repo that git itself will accept.

    Catches the case where a previous failed run left an empty or
    half-populated directory — ``(clone / ".git").is_dir()`` would
    accept it but any subsequent git command would fail.
    """
    if not clone.exists():
        return False
    r = _run(["git", "rev-parse", "--git-dir"], cwd=clone)
    return r.returncode == 0


def dispatch_git(dest: DestinationSpec, upload: Upload, work_root: Path) -> str:
    """Commit-and-push the artefact into a bare-remote git repository.

    The local clone lives under ``<work_root>/git-<id>`` and is reused
    across runs — we don't re-clone every time. If the repo has no
    commits (fresh clone of an empty remote), we initialize it with a
    commit before pushing.

    .. note::

       Git stores every artefact as a blob in ``.git/objects`` **forever**.
       With daily runs on a moderately-sized source, the remote repo
       grows by (artefact size) per day regardless of whether the
       content changed — because even a no-op commit costs a new pointer
       in the pack.

       This is by design for this backend: the git kind gives you a
       full, auditable version history, and that history is exactly
       what bounds the storage. If you want bounded growth and don't
       need history, use ``kind = "local"`` with ``retain = N`` or
       ``kind = "s3"`` with an S3 lifecycle rule — those destinations
       can drop old artefacts, git cannot.
    """
    if not dest.remote:
        raise DestinationError(f"git dest {dest.id!r}: missing 'remote'")
    branch = dest.branch or "main"

    clone = work_root / f"git-{dest.id}"
    clone.parent.mkdir(parents=True, exist_ok=True)

    # A bare "is the .git dir present" check isn't enough — a prior
    # failed run can leave a half-initialized repo that subsequent git
    # commands reject. Verify with a real git call, and reset if broken.
    if not _is_valid_git_repo(clone):
        shutil.rmtree(clone, ignore_errors=True)
        clone.mkdir(parents=True, exist_ok=True)
        # Try clone first — the happy path for any non-empty remote.
        r = _run(["git", "clone", "--depth", "1", dest.remote, str(clone)])
        if r.returncode != 0:
            # Empty remote (or unreachable during this pass) — initialize
            # locally and let the subsequent push publish the first ref.
            shutil.rmtree(clone, ignore_errors=True)
            clone.mkdir(parents=True, exist_ok=True)
            r = _run(["git", "init", "-b", branch], cwd=clone)
            if r.returncode != 0:
                raise DestinationError(f"git dest {dest.id!r}: init failed: {r.stderr.strip()}")
            r = _run(["git", "remote", "add", "origin", dest.remote], cwd=clone)
            if r.returncode != 0:
                raise DestinationError(
                    f"git dest {dest.id!r}: remote add failed: {r.stderr.strip()}"
                )

    # Make sure we're on the right branch (checkout --orphan if brand new).
    r = _run(["git", "rev-parse", "--verify", branch], cwd=clone)
    if r.returncode != 0:
        r = _run(["git", "checkout", "--orphan", branch], cwd=clone)
        if r.returncode != 0:
            raise DestinationError(f"git dest {dest.id!r}: checkout failed: {r.stderr.strip()}")
    else:
        r = _run(["git", "checkout", branch], cwd=clone)
        if r.returncode != 0:
            raise DestinationError(f"git dest {dest.id!r}: checkout failed: {r.stderr.strip()}")

    dest_file = clone / upload.artefact.name
    try:
        shutil.copy2(upload.artefact, dest_file)
    except OSError as exc:
        raise DestinationError(f"git dest {dest.id!r}: copy into clone failed: {exc}") from exc

    _run(["git", "add", dest_file.name], cwd=clone)
    # If nothing actually changed (same content → same filename since the
    # filename includes the digest), commit will return non-zero; treat
    # that as a successful no-op.
    commit_msg = f"backup: {upload.source_id}@{upload.digest[:12]} {datetime.now(UTC).isoformat()}"
    r = _run(["git", "commit", "-m", commit_msg], cwd=clone)
    if r.returncode != 0:
        if "nothing to commit" in (r.stdout + r.stderr).lower():
            return f"no-op (unchanged) on {dest.remote}"
        raise DestinationError(f"git dest {dest.id!r}: commit failed: {r.stderr.strip()}")

    r = _run(["git", "push", "origin", branch], cwd=clone)
    if r.returncode != 0:
        # Try --set-upstream for first-push case.
        r2 = _run(["git", "push", "--set-upstream", "origin", branch], cwd=clone)
        if r2.returncode != 0:
            raise DestinationError(f"git dest {dest.id!r}: push failed: {r2.stderr.strip()}")

    return f"pushed to {dest.remote}#{branch}"


# --------- s3 ----------------------------------------------------------


def dispatch_s3(dest: DestinationSpec, upload: Upload) -> str:
    """Shell out to ``aws s3 cp``.

    The AWS CLI honours its own environment (AWS_PROFILE,
    AWS_ACCESS_KEY_ID, ~/.aws/credentials, IAM roles, etc.). We do not
    re-implement credential resolution.
    """
    if not dest.bucket:
        raise DestinationError(f"s3 dest {dest.id!r}: missing 'bucket'")
    key = (dest.prefix or "") + upload.artefact.name
    s3_uri = f"s3://{dest.bucket}/{key}"

    argv = ["aws", "s3", "cp", str(upload.artefact), s3_uri, "--no-progress"]
    if dest.s3_endpoint:
        argv.extend(["--endpoint-url", dest.s3_endpoint])

    r = _run(argv)
    if r.returncode != 0:
        raise DestinationError(f"s3 dest {dest.id!r}: cp failed: {r.stderr.strip()}")
    return f"uploaded to {s3_uri}"
