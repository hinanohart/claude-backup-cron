"""CLI happy-path smoke tests — writes a tmp config, runs subcommands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_backup_cron.cli import main


def _write_config(tmp_path: Path, src: Path, dest: Path) -> Path:
    # Use POSIX-style paths in TOML so Windows backslashes aren't
    # interpreted as TOML escape sequences.
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[[sources]]\n"
        f'id = "s1"\npath = "{src.as_posix()}"\n'
        "\n"
        "[[destinations]]\n"
        f'id = "d1"\nkind = "local"\npath = "{dest.as_posix()}"\n'
        f'\n[global]\nstate_dir = "{(tmp_path / "state").as_posix()}"\n',
        encoding="utf-8",
    )
    return cfg


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["version"])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out.count(".") >= 2  # semver-looking


def test_show_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hi", encoding="utf-8")
    cfg = _write_config(tmp_path, src, tmp_path / "dst")
    rc = main(["--config", str(cfg), "show-config"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "s1" in out
    assert "d1" in out
    assert "(local)" in out


def test_run_happy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hi", encoding="utf-8")
    dest = tmp_path / "dst"
    cfg = _write_config(tmp_path, src, dest)
    rc = main(["--config", str(cfg), "run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "[OK]" in out
    assert any(dest.iterdir())


def test_run_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hi", encoding="utf-8")
    cfg = _write_config(tmp_path, src, tmp_path / "dst")
    rc = main(["--config", str(cfg), "run", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["ok"] is True
    assert len(data["results"]) == 1


def test_run_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("hi", encoding="utf-8")
    dest = tmp_path / "dst"
    cfg = _write_config(tmp_path, src, dest)
    rc = main(["--config", str(cfg), "run", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry-run" in out
    assert not dest.exists() or not any(dest.iterdir())


def test_run_failure_exit_code_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Missing source → packaging fails → exit 2
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[[sources]]\nid = "gone"\npath = "/this/does/not/exist"\n'
        '\n[[destinations]]\nid = "d"\nkind = "local"\npath = "'
        + (tmp_path / "out").as_posix()
        + '"\n',
        encoding="utf-8",
    )
    rc = main(["--config", str(cfg), "run"])
    capsys.readouterr()
    assert rc == 2


def test_missing_config_exit_code_3(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--config", str(tmp_path / "nope.toml"), "run"])
    err = capsys.readouterr().err
    assert rc == 3
    assert "not found" in err.lower()
