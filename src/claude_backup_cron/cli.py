"""Command-line interface.

Subcommands:

* ``run``          — execute the backup plan.
* ``show-config``  — print the resolved config (masking the webhook).
* ``install-cron`` — register a cron entry for ``run``.
* ``uninstall-cron`` — remove the managed cron entry.
* ``version``      — print the package version.

``run`` is the one the cron job calls. It exits 0 on full success, 2 if
any step failed, and 3 on config/encryption errors that prevented the
run from starting.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from claude_backup_cron import backup, config, encryption, scheduler
from claude_backup_cron._version import __version__
from claude_backup_cron.errors import BackupError, SchedulerError

if TYPE_CHECKING:
    from collections.abc import Sequence

_LOG = logging.getLogger("claude_backup_cron")

_EXIT_OK = 0
_EXIT_STEP_FAILURE = 2
_EXIT_SETUP_FAILURE = 3


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="claude-backup-cron",
        description="Scheduled encrypted backups for Claude Code's memory and similar small directories.",
    )
    ap.add_argument("--config", type=Path, help="Override config path.")
    ap.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Emit INFO-level logs on stderr.",
    )

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Execute the backup plan.")
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Package sources but skip encryption and uploads.",
    )
    p_run.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report on stdout instead of a human summary.",
    )

    sub.add_parser("show-config", help="Print the resolved config.")

    p_install = sub.add_parser("install-cron", help="Install (or replace) the cron entry.")
    p_install.add_argument(
        "--schedule",
        required=True,
        help='Cron expression, e.g. "0 3 * * *" for daily 03:00.',
    )

    sub.add_parser("uninstall-cron", help="Remove the managed cron entry.")
    sub.add_parser("version", help="Print the package version.")

    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = _build_parser()
    ns = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if ns.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if ns.cmd == "version":
        print(__version__)
        return _EXIT_OK

    if ns.cmd == "install-cron":
        return _cmd_install_cron(ns.schedule)
    if ns.cmd == "uninstall-cron":
        return _cmd_uninstall_cron()

    # show-config / run both need a loaded config.
    try:
        cfg = config.load(path=ns.config)
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_SETUP_FAILURE

    if ns.cmd == "show-config":
        return _cmd_show_config(cfg)
    if ns.cmd == "run":
        return _cmd_run(cfg, dry_run=ns.dry_run, as_json=ns.json)

    ap.error(f"unknown cmd {ns.cmd!r}")  # pragma: no cover — argparse has already rejected this
    return _EXIT_SETUP_FAILURE


def _cmd_show_config(cfg: config.Config) -> int:
    print(f"config: {cfg.source_path}")
    print(f"state_dir: {cfg.global_.state_dir}")
    print(f"alert_webhook: {'<set>' if cfg.global_.alert_webhook else '<unset>'}")
    print(f"age available: {encryption.age_available()}")
    print("sources:")
    for s in cfg.sources:
        print(f"  - {s.id}: {s.path} (exclude={list(s.exclude)})")
    print("destinations:")
    for d in cfg.destinations:
        detail = []
        if d.remote:
            detail.append(f"remote={d.remote}")
        if d.bucket:
            detail.append(f"bucket={d.bucket}")
            if d.prefix:
                detail.append(f"prefix={d.prefix}")
        if d.path:
            detail.append(f"path={d.path}")
        if d.encrypt_to:
            detail.append("encrypted")
        print(f"  - {d.id} ({d.kind}): {' '.join(detail)}")
    if cfg.extra_keys:
        print(f"warning: unknown top-level keys ignored: {list(cfg.extra_keys)}")
    return _EXIT_OK


def _cmd_run(cfg: config.Config, *, dry_run: bool, as_json: bool) -> int:
    try:
        report = backup.run(cfg, dry_run=dry_run)
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_SETUP_FAILURE

    if as_json:
        print(
            json.dumps(
                {
                    "dry_run": report.dry_run,
                    "ok": report.ok,
                    "results": [
                        {
                            "source_id": r.source_id,
                            "destination_id": r.destination_id,
                            "ok": r.ok,
                            "message": r.message,
                        }
                        for r in report.results
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for r in report.results:
            tag = "OK" if r.ok else "FAIL"
            print(f"[{tag}] {r.source_id} → {r.destination_id}: {r.message}")
        if not report.results:
            print("(no steps executed — check your sources/destinations.)")
        print(
            f"summary: {sum(1 for r in report.results if r.ok)} ok, "
            f"{sum(1 for r in report.results if not r.ok)} failed"
        )

    return _EXIT_OK if report.ok else _EXIT_STEP_FAILURE


def _cmd_install_cron(schedule: str) -> int:
    try:
        block = scheduler.install(schedule)
    except SchedulerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_SETUP_FAILURE
    print("installed cron entry:")
    print(block)
    return _EXIT_OK


def _cmd_uninstall_cron() -> int:
    try:
        removed = scheduler.uninstall()
    except SchedulerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_SETUP_FAILURE
    print("removed" if removed else "nothing to remove")
    return _EXIT_OK
