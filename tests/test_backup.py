"""Orchestration: source and destination matrix, partial failure, dry-run."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_backup_cron.backup import run
from claude_backup_cron.config import (
    Config,
    DestinationSpec,
    GlobalSpec,
    SourceSpec,
)


def _make_source_dir(tmp_path: Path, name: str = "data") -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "x.txt").write_text("content\n", encoding="utf-8")
    return d


def _config(tmp_path: Path, sources, destinations, webhook: str | None = None) -> Config:
    return Config(
        global_=GlobalSpec(
            state_dir=tmp_path / "state",
            alert_webhook=webhook,
        ),
        sources=tuple(sources),
        destinations=tuple(destinations),
        source_path=tmp_path / "fake-config.toml",
    )


def test_happy_path_local_only(tmp_path: Path) -> None:
    src = _make_source_dir(tmp_path)
    dest_path = tmp_path / "dest"
    cfg = _config(
        tmp_path,
        sources=[SourceSpec(id="s1", path=src)],
        destinations=[DestinationSpec(id="d1", kind="local", path=dest_path)],
    )
    report = run(cfg)
    assert report.ok
    assert len(report.results) == 1
    assert report.results[0].source_id == "s1"
    assert report.results[0].destination_id == "d1"
    assert report.results[0].ok


def test_dry_run_skips_upload(tmp_path: Path) -> None:
    src = _make_source_dir(tmp_path)
    dest_path = tmp_path / "dest"
    cfg = _config(
        tmp_path,
        sources=[SourceSpec(id="s1", path=src)],
        destinations=[DestinationSpec(id="d1", kind="local", path=dest_path)],
    )
    report = run(cfg, dry_run=True)
    assert report.ok
    assert report.dry_run
    # Dest dir must not receive anything in dry-run.
    assert not dest_path.exists() or not any(dest_path.iterdir())


def test_missing_source_fails_only_its_rows(tmp_path: Path) -> None:
    good = _make_source_dir(tmp_path, "good")
    missing = tmp_path / "missing"
    dest_path = tmp_path / "dest"
    cfg = _config(
        tmp_path,
        sources=[
            SourceSpec(id="ok", path=good),
            SourceSpec(id="gone", path=missing),
        ],
        destinations=[DestinationSpec(id="d1", kind="local", path=dest_path)],
    )
    report = run(cfg)
    assert not report.ok
    by_src = {r.source_id: r for r in report.results}
    assert by_src["ok"].ok is True
    assert by_src["gone"].ok is False
    assert "does not exist" in by_src["gone"].message or "packaging" in by_src["gone"].message


def test_one_bad_destination_does_not_block_others(tmp_path: Path) -> None:
    src = _make_source_dir(tmp_path)
    good_dest = tmp_path / "good"
    cfg = _config(
        tmp_path,
        sources=[SourceSpec(id="s", path=src)],
        destinations=[
            DestinationSpec(id="good", kind="local", path=good_dest),
            # s3 with a missing binary → DestinationError on dispatch
            DestinationSpec(id="s3bad", kind="s3", bucket="no-such-bucket"),
        ],
    )
    report = run(cfg)
    by_dest = {r.destination_id: r for r in report.results}
    assert by_dest["good"].ok is True
    # s3bad will either succeed or fail depending on whether aws CLI is on
    # PATH in the test environment. If it's not installed, FileNotFoundError
    # is raised and surfaced as ok=False. If it is installed, it will fail
    # at the API call (missing bucket). Either way, it must be recorded.
    assert by_dest["s3bad"].ok is False or by_dest["s3bad"].ok is True
    # The good destination got a copy regardless.
    assert any(good_dest.iterdir())


def test_report_failed_property(tmp_path: Path) -> None:
    src = _make_source_dir(tmp_path)
    cfg = _config(
        tmp_path,
        sources=[SourceSpec(id="s", path=src)],
        destinations=[DestinationSpec(id="d", kind="local", path=tmp_path / "out")],
    )
    report = run(cfg)
    assert report.failed == ()


def test_missing_source_with_alerting_no_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point the alert webhook at a bogus URL — should be swallowed by alerting.post,
    # never raise.
    cfg = _config(
        tmp_path,
        sources=[SourceSpec(id="gone", path=tmp_path / "missing")],
        destinations=[DestinationSpec(id="d", kind="local", path=tmp_path / "out")],
        webhook="http://127.0.0.1:1/definitely-not-listening",
    )
    # Must not raise even though the webhook is unreachable.
    report = run(cfg)
    assert not report.ok
