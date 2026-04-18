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

import re
import shutil
import subprocess
from pathlib import Path

from claude_backup_cron.errors import EncryptionError

# ``age`` accepts two recipient shapes:
#   * X25519 ``age1…`` bech32 (``age-keygen`` output)
#   * SSH public key — ``ssh-rsa …`` / ``ssh-ed25519 …`` / ``ecdsa-…``
# Validate both; reject garbage like random strings or shell metachars.
_AGE_RECIPIENT_RE = re.compile(
    r"\A(?:"
    r"age1[0-9a-z]{20,}"
    r"|ssh-(?:rsa|ed25519)\s+[A-Za-z0-9+/=]+(?:\s+\S+)?"
    r"|ecdsa-sha2-[a-z0-9-]+\s+[A-Za-z0-9+/=]+(?:\s+\S+)?"
    r")\Z"
)

# ``age --version`` may emit any of:
#   v1.2.0          (upstream build)
#   1.2.0           (Homebrew formula)
#   age version 1.1.1 (some distro packaging)
#   v2.0.0          (hypothetical future release; accept)
# Extract the first ``[v]?MAJOR.MINOR`` and require MAJOR >= 1.
_AGE_VERSION_RE = re.compile(r"(?:^|\s)v?(\d+)\.(\d+)(?:\.\d+)?")


def age_available() -> bool:
    """Return True iff the ``age`` binary on ``PATH`` looks genuine.

    ``shutil.which("age")`` alone is not enough: if ``$PATH`` contains a
    user-writable directory before the system binary, an attacker who
    lands code execution can plant an ``age`` shim that silently writes
    plaintext under an ``.age`` filename. We additionally probe
    ``age --version`` and require the output to name at least version 1.

    The ``--version`` output is checked on both stdout and stderr because
    different packaging flavours target different streams.
    """
    path = shutil.which("age")
    if path is None:
        return False
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell.
            [path, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    m = _AGE_VERSION_RE.search(combined)
    if m is None:
        return False
    return int(m.group(1)) >= 1


def encrypt_file(src: Path, dst: Path, recipient: str) -> None:
    """Encrypt ``src`` to ``dst`` using the given age recipient.

    Raises :class:`EncryptionError` on any failure. We deliberately do
    not fall back to plaintext — the whole point of ``encrypt_to`` is
    that the destination should never see plaintext.
    """
    if not age_available():
        raise EncryptionError(
            "age binary not found (or not a recognised age v1 build) on "
            "PATH. Install the official age from https://age-encryption.org/ "
            "or drop the 'encrypt_to' key if you genuinely want unencrypted "
            "uploads."
        )
    if not _AGE_RECIPIENT_RE.match(recipient):
        raise EncryptionError(
            f"encrypt: recipient does not look like an age public key "
            f"(expected ``age1...`` bech32, got {recipient[:12]!r})"
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
