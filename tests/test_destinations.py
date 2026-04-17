"""Destination dispatch — local and git happy paths, failure modes.

The git tests use a real bare repo on disk (no network). S3 is tested
only for config-validation; we don't spin up a real S3 endpoint in CI.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from claude_backup_cron.config import DestinationSpec
from claude_backup_cron.destinations import (
    Upload,
    dispatch_git,
    dispatch_local,
    dispatch_s3,
)
from claude_backup_cron.errors import DestinationError

_HAS_GIT = shutil.which("git") is not None


def _make_artefact(tmp_path: Path, name: str = "src-abc123.tar") -> Path:
    p = tmp_path / name
    p.write_bytes(b"payload")
    return p


def _upload(artefact: Path, source_id: str = "src", digest: str = "abc123") -> Upload:
    return Upload(source_id=source_id, digest=digest, artefact=artefact, encrypted=False)


# --------- local -------------------------------------------------------


def test_local_copy(tmp_path: Path) -> None:
    artefact = _make_artefact(tmp_path)
    dest_path = tmp_path / "dest"
    spec = DestinationSpec(id="d", kind="local", path=dest_path)
    msg = dispatch_local(spec, _upload(artefact))
    assert (dest_path / artefact.name).read_bytes() == b"payload"
    assert "copied" in msg


def test_local_creates_parent_dir(tmp_path: Path) -> None:
    artefact = _make_artefact(tmp_path)
    deep = tmp_path / "a" / "b" / "c"
    spec = DestinationSpec(id="d", kind="local", path=deep)
    dispatch_local(spec, _upload(artefact))
    assert (deep / artefact.name).exists()


def test_local_retain_prunes_old(tmp_path: Path) -> None:
    dest = tmp_path / "dst"
    dest.mkdir()
    # Pre-seed with 4 old artefacts for the same source.
    import time

    for i in range(4):
        p = dest / f"src-oldhash{i}.tar"
        p.write_bytes(b"old")
        ts = time.time() - (10 - i)  # newer as i grows
        import os

        os.utime(p, (ts, ts))

    newest = _make_artefact(tmp_path, "src-newhash.tar")
    spec = DestinationSpec(id="d", kind="local", path=dest, retain=2)
    dispatch_local(spec, _upload(newest))

    remaining = sorted(p.name for p in dest.iterdir() if p.name.startswith("src-"))
    assert len(remaining) == 2
    # Newest should always survive.
    assert "src-newhash.tar" in remaining


# --------- git ---------------------------------------------------------


@pytest.mark.skipif(not _HAS_GIT, reason="git not available on PATH")
def test_git_push_to_bare_remote(tmp_path: Path) -> None:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)

    artefact = _make_artefact(tmp_path)
    work = tmp_path / "work"
    spec = DestinationSpec(id="gh", kind="git", remote=str(bare), branch="main")

    msg = dispatch_git(spec, _upload(artefact), work)
    assert "pushed" in msg or "main" in msg

    # Second run with the same digest → filename is identical, so git sees
    # "nothing to commit" and should short-circuit gracefully.
    msg2 = dispatch_git(spec, _upload(artefact), work)
    assert "no-op" in msg2 or "unchanged" in msg2


@pytest.mark.skipif(not _HAS_GIT, reason="git not available on PATH")
def test_git_push_failure_surfaced(tmp_path: Path) -> None:
    artefact = _make_artefact(tmp_path)
    work = tmp_path / "work"
    spec = DestinationSpec(
        id="bad",
        kind="git",
        remote=str(tmp_path / "does-not-exist.git"),
        branch="main",
    )
    with pytest.raises(DestinationError):
        dispatch_git(spec, _upload(artefact), work)


# --------- s3 ----------------------------------------------------------


def test_s3_missing_bucket_is_config_error(tmp_path: Path) -> None:
    artefact = _make_artefact(tmp_path)
    spec = DestinationSpec(id="s", kind="s3")
    with pytest.raises(DestinationError, match="bucket"):
        dispatch_s3(spec, _upload(artefact))


def test_s3_missing_cli_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Point PATH at a directory that does not contain `aws`.
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    artefact = _make_artefact(tmp_path)
    spec = DestinationSpec(id="s", kind="s3", bucket="my-bucket", prefix="pre/")
    with pytest.raises(DestinationError):
        dispatch_s3(spec, _upload(artefact))
