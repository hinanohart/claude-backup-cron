"""Source packaging: deterministic tarball, digest stability, exclude."""

from __future__ import annotations

import hashlib
import tarfile
from pathlib import Path

import pytest

from claude_backup_cron.config import SourceSpec
from claude_backup_cron.errors import SourceError
from claude_backup_cron.sources import package


def _make_source(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    (root / "a.txt").write_text("hello\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "b.txt").write_text("world\n", encoding="utf-8")
    (root / "sub" / "ignore.swp").write_text("junk\n", encoding="utf-8")
    return root


def test_package_creates_tar(tmp_path: Path) -> None:
    root = _make_source(tmp_path)
    spec = SourceSpec(id="demo", path=root)
    out = tmp_path / "out"
    artefact = package(spec, out)
    assert artefact.path.exists()
    assert artefact.path.suffix == ".tar"
    assert artefact.digest.isalnum() and len(artefact.digest) == 64

    with tarfile.open(artefact.path) as tf:
        names = sorted(tf.getnames())
    assert "demo/a.txt" in names
    assert "demo/sub/b.txt" in names


def test_exclude_glob_drops_entries(tmp_path: Path) -> None:
    root = _make_source(tmp_path)
    spec = SourceSpec(id="demo", path=root, exclude=("sub/*.swp",))
    artefact = package(spec, tmp_path / "out")
    with tarfile.open(artefact.path) as tf:
        names = tf.getnames()
    assert "demo/sub/ignore.swp" not in names
    assert "demo/sub/b.txt" in names


def test_tar_bytes_deterministic_across_runs(tmp_path: Path) -> None:
    root = _make_source(tmp_path)
    spec = SourceSpec(id="demo", path=root)

    out1 = tmp_path / "out1"
    artefact1 = package(spec, out1)
    bytes1 = artefact1.path.read_bytes()
    hash1 = hashlib.sha256(bytes1).hexdigest()

    # Clobber mtime on every file, then repackage into a fresh out dir.
    import os

    for p in root.rglob("*"):
        if p.is_file():
            os.utime(p, (10_000, 10_000))

    out2 = tmp_path / "out2"
    artefact2 = package(spec, out2)
    hash2 = hashlib.sha256(artefact2.path.read_bytes()).hexdigest()
    assert hash1 == hash2, "tar bytes must be stable across runs"


def test_reuses_existing_artefact(tmp_path: Path) -> None:
    root = _make_source(tmp_path)
    spec = SourceSpec(id="demo", path=root)
    out = tmp_path / "out"

    first = package(spec, out)
    first_mtime = first.path.stat().st_mtime_ns

    import time

    time.sleep(0.01)

    second = package(spec, out)
    assert second.path == first.path
    # Re-running with identical input must not rewrite the file.
    assert second.path.stat().st_mtime_ns == first_mtime


def test_missing_source_raises(tmp_path: Path) -> None:
    spec = SourceSpec(id="nope", path=tmp_path / "missing")
    with pytest.raises(SourceError):
        package(spec, tmp_path / "out")
