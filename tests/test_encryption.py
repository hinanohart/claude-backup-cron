"""age encryption wrapper.

Full round-trip tests require the ``age`` binary, so we guard them with
a skip. The error-path tests exercise the failure modes without needing
the binary itself.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from claude_backup_cron import encryption
from claude_backup_cron.errors import EncryptionError

_HAS_AGE = shutil.which("age") is not None


def test_available_reflects_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert encryption.age_available() is False


def test_encrypt_missing_age_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    src = tmp_path / "plain.tar"
    src.write_bytes(b"payload")
    dst = tmp_path / "plain.tar.age"
    with pytest.raises(EncryptionError, match="age binary"):
        encryption.encrypt_file(src, dst, recipient="age1abc")


def test_encrypt_missing_source(tmp_path: Path) -> None:
    if not _HAS_AGE:
        pytest.skip("age not installed")
    with pytest.raises(EncryptionError):
        encryption.encrypt_file(
            tmp_path / "does-not-exist",
            tmp_path / "out.age",
            recipient="age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        )


@pytest.mark.skipif(not _HAS_AGE, reason="age binary not available")
def test_encrypt_roundtrip(tmp_path: Path) -> None:
    # Generate a throwaway key pair.
    keyfile = tmp_path / "age.key"
    kp = subprocess.run(
        ["age-keygen", "-o", str(keyfile)],
        capture_output=True,
        text=True,
        check=False,
    )
    if kp.returncode != 0:
        pytest.skip("age-keygen not available")
    recipient = None
    for line in (kp.stderr + kp.stdout).splitlines():
        if line.startswith("Public key:"):
            recipient = line.split(":", 1)[1].strip()
            break
    if not recipient:
        pytest.skip("could not parse age-keygen output")

    src = tmp_path / "plain.tar"
    payload = b"secret bytes"
    src.write_bytes(payload)
    dst = tmp_path / "plain.tar.age"

    encryption.encrypt_file(src, dst, recipient=recipient)
    assert dst.stat().st_size > 0
    assert dst.read_bytes() != payload  # actually encrypted

    # Decrypt and compare.
    r = subprocess.run(
        ["age", "--decrypt", "-i", str(keyfile), str(dst)],
        capture_output=True,
        check=False,
    )
    assert r.returncode == 0
    assert r.stdout == payload
