"""Install / inspect a cron entry for the backup.

systemd units are intentionally *not* supported in this release: the
user base is Claude Code individuals, and every supported OS ships cron.
A systemd timer generator can be added later without breaking the
public config.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from claude_backup_cron.errors import SchedulerError

_MARKER = "# claude-backup-cron managed entry"

# Classic 5-field (``m h dom mon dow``) or Vixie 6-field (with seconds) cron
# expressions. Each field is digits, ``*``, ``/`` (step), ``-`` (range),
# ``,`` (list), ``?`` (either-of in some implementations), or letter names
# (``JAN``-``DEC``, ``MON``-``SUN``, case-insensitive).
#
# Aliases like ``@hourly`` / ``@daily`` / ``@weekly`` / ``@monthly`` /
# ``@yearly`` / ``@annually`` / ``@reboot`` / ``@every 5m`` (Vixie) are also
# accepted.
#
# The strict regex exists specifically to block ``schedule="* * * * *; rm
# -rf ~"``-style command-injection — whatever the user types here lands in
# the crontab verbatim, and on most cron variants anything after the 5th
# field is the command.
_CRON_FIELD = r"[0-9A-Za-z*/,?\-]+"
_CRON_EXPRESSION_RE = re.compile(
    rf"\A\s*(?:"
    rf"@(?:reboot|hourly|daily|weekly|monthly|yearly|annually|midnight)"
    rf"|{_CRON_FIELD}(?:\s+{_CRON_FIELD}){{4,5}}"
    rf")\s*\Z"
)


def _validate_schedule(schedule: str) -> None:
    """Reject anything that isn't a pure 5/6-field cron expression or @alias.

    Refuses embedded shell metacharacters (``;``, ``|``, ``&``, backticks,
    ``$(...)``) that would inject commands into the crontab line.
    """
    if not _CRON_EXPRESSION_RE.fullmatch(schedule):
        raise SchedulerError(
            f"invalid schedule: {schedule!r}. Expected a 5-field cron "
            "expression (e.g. '0 3 * * *') or a @alias (e.g. '@daily'). "
            "Shell metacharacters are rejected to prevent crontab injection."
        )


def _run_crontab(args: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 — fixed argv.
            ["crontab", *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SchedulerError("crontab binary not found on PATH") from exc


def read_current() -> str:
    """Return the current user's crontab, or empty string if none is set."""
    if shutil.which("crontab") is None:
        raise SchedulerError("crontab binary not found on PATH")
    r = _run_crontab(["-l"])
    if r.returncode != 0:
        stderr = r.stderr.lower()
        if "no crontab" in stderr or "cannot read" in stderr:
            return ""
        raise SchedulerError(f"crontab -l failed: {r.stderr.strip()}")
    return r.stdout


def _strip_managed_block(existing: str) -> str:
    """Remove any previous managed block (both its marker and command line)."""
    out_lines: list[str] = []
    skip_next = False
    for line in existing.splitlines():
        if skip_next:
            skip_next = False
            continue
        if line.strip() == _MARKER:
            skip_next = True
            continue
        out_lines.append(line)
    return "\n".join(out_lines).rstrip("\n")


def install(schedule: str, *, binary: str | None = None) -> str:
    """Install (or update) the cron entry.

    The entry is two lines: our marker comment, then the schedule +
    command. Re-installing is idempotent — any previous managed block is
    replaced.
    """
    if not schedule.strip():
        raise SchedulerError("schedule must be a non-empty cron expression")
    _validate_schedule(schedule)
    resolved_binary = binary or shutil.which("claude-backup-cron")
    if not resolved_binary:
        raise SchedulerError(
            "claude-backup-cron binary not found on PATH — activate the "
            "venv or pipx install first, then re-run install-cron."
        )
    existing = read_current()
    stripped = _strip_managed_block(existing)

    # Preserve LANG/PATH the user set in their crontab header, if any.
    command_line = f"{schedule} {resolved_binary} run >> {_logfile()} 2>&1"
    new_block = f"{_MARKER}\n{command_line}"
    combined = (stripped + "\n\n" + new_block + "\n").lstrip("\n") if stripped else new_block + "\n"

    r = _run_crontab(["-"], stdin=combined)
    if r.returncode != 0:
        raise SchedulerError(f"crontab install failed: {r.stderr.strip()}")
    return new_block


def uninstall() -> bool:
    """Remove the managed entry. Returns True if something was removed."""
    existing = read_current()
    if _MARKER not in existing:
        return False
    stripped = _strip_managed_block(existing)
    combined = (stripped + "\n") if stripped else ""
    r = _run_crontab(["-"], stdin=combined)
    if r.returncode != 0:
        raise SchedulerError(f"crontab uninstall failed: {r.stderr.strip()}")
    return True


def _logfile() -> str:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = xdg if xdg else os.path.expanduser("~/.local/state")
    return f"{base}/claude-backup-cron/cron.log"
