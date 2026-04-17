"""Scheduled, encrypted backups for small but high-value directories.

Designed for Claude Code's memory folder and comparable caches: single
user, one or two sources, a handful of destinations (private git remote,
S3 bucket, local spare drive), age encryption on the wire, webhook
alerts on failure. Zero runtime deps on Python 3.11+.
"""

from __future__ import annotations

from claude_backup_cron._version import __version__
from claude_backup_cron.backup import RunReport, StepResult, run
from claude_backup_cron.config import (
    Config,
    DestinationSpec,
    GlobalSpec,
    SourceSpec,
    load,
)
from claude_backup_cron.destinations import Upload
from claude_backup_cron.errors import (
    BackupError,
    ConfigError,
    DestinationError,
    EncryptionError,
    SchedulerError,
    SourceError,
)
from claude_backup_cron.sources import Artefact

__all__ = [
    "Artefact",
    "BackupError",
    "Config",
    "ConfigError",
    "DestinationError",
    "DestinationSpec",
    "EncryptionError",
    "GlobalSpec",
    "RunReport",
    "SchedulerError",
    "SourceError",
    "SourceSpec",
    "StepResult",
    "Upload",
    "__version__",
    "load",
    "run",
]
