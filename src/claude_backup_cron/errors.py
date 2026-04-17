"""Typed exceptions for the package.

The CLI catches these at the top level and converts them into a single
exit code plus (optionally) an alerting webhook POST. Library users can
pattern-match on the specific subclass to decide whether to retry, warn,
or re-raise.
"""

from __future__ import annotations


class BackupError(RuntimeError):
    """Base class for all backup-related failures."""


class ConfigError(BackupError):
    """Raised when the config file is missing, malformed, or inconsistent."""


class SourceError(BackupError):
    """Raised when reading a source path fails (missing path, permission, etc.)."""


class EncryptionError(BackupError):
    """Raised when ``age`` is unavailable or fails mid-encryption.

    Always fatal for the affected destination; we deliberately do not fall
    back to unencrypted output, because silent downgrades of the threat
    model are exactly the class of bug this package exists to avoid.
    """


class DestinationError(BackupError):
    """Raised when a destination rejects the upload.

    Each destination is tried independently — one failure does not abort
    the run. The CLI surfaces a non-zero exit only if *every* destination
    fails (or if there was a config/encryption error upstream).
    """


class SchedulerError(BackupError):
    """Raised when installing / inspecting the cron or systemd unit fails."""
