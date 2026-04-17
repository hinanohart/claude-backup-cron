"""Encryption wrapper around the ``age`` CLI.

We shell out to ``age`` rather than depend on a Python implementation for
three reasons:

1. ``age`` is the canonical implementation; its format is audited and
   stable. A third-party Python port is another moving part that must be
   trusted.
2. Installing ``age`` is trivial on every platform we care about
   (``apt``, ``brew``, ``pacman``, ``scoop``). Requiring it is cheaper
   than maintaining a shadow implementation.
3. Keeping the dependency graph at zero pure-Python crypto libraries
   avoids the bullseye for supply-chain attacks on backup tooling.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from claude_backup_cron.errors import EncryptionError


def age_available() -> bool:
    """Return True iff the ``age`` binary is on ``PATH``."""
    return shutil.which("age") is not None


def encrypt_file(src: Path, dst: Path, recipient: str) -> None:
    """Encrypt ``src`` to ``dst`` using the given age recipient.

    Raises :class:`EncryptionError` on any failure. We deliberately do
    not fall back to plaintext — the whole point of ``encrypt_to`` is
    that the destination should never see plaintext.
    """
    if not age_available():
        raise EncryptionError(
            "age binary not found on PATH. Install from "
            "https://age-encryption.org/ or drop the 'encrypt_to' key "
            "if you genuinely want unencrypted uploads."
        )
    if not src.is_file():
        raise EncryptionError(f"encrypt: source does not exist: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell.
            ["age", "--recipient", recipient, "--output", str(dst), str(src)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise EncryptionError("age binary disappeared between check and call") from exc
    if proc.returncode != 0:
        raise EncryptionError(
            f"age exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    if not dst.is_file() or dst.stat().st_size == 0:
        raise EncryptionError(f"age produced no output at {dst}")
