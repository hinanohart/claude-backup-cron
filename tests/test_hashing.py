"""Hash-tree behaviour: determinism, exclusion, sensitivity to renames."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_backup_cron.hashing import hash_tree


def _seed(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("beta", encoding="utf-8")
    return tmp_path


def test_hash_stable_across_calls(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    h1 = hash_tree(root)
    h2 = hash_tree(root)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_hash_changes_when_content_changes(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    before = hash_tree(root)
    (root / "a.txt").write_text("alpha+one", encoding="utf-8")
    assert hash_tree(root) != before


def test_hash_changes_when_path_changes(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    before = hash_tree(root)
    (root / "a.txt").rename(root / "renamed.txt")
    assert hash_tree(root) != before


def test_hash_empty_dir_is_not_the_same_as_missing_file(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    (tmp_path / "y" / "present.txt").write_text("hi", encoding="utf-8")
    assert hash_tree(tmp_path / "x") != hash_tree(tmp_path / "y")


def test_exclude_glob_is_honoured(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    base = hash_tree(root)
    (root / "sub" / "noise.swp").write_text("swap", encoding="utf-8")
    assert hash_tree(root, excludes=("sub/*.swp",)) == base
    assert hash_tree(root) != base  # without the exclude, change is visible


def test_single_file_root(tmp_path: Path) -> None:
    f = tmp_path / "only.txt"
    f.write_text("hello", encoding="utf-8")
    assert len(hash_tree(f)) == 64


def test_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        hash_tree(tmp_path / "does-not-exist")


def test_symlinks_are_skipped_not_followed(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    before = hash_tree(root)
    target = root / "sub" / "b.txt"
    (root / "link-to-b").symlink_to(target)
    # Symlink addition must not change the hash (symlinks are skipped).
    assert hash_tree(root) == before
