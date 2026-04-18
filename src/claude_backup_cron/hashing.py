"""Content hashing for change detection.

Walk a directory, hash every file's bytes + its relative path, return a
single SHA-256 digest. Used to decide whether the backup has changed
since the last run — if not, the whole run is a no-op and no
destinations are contacted.

Design notes
------------

* **Include the relative path** in the hash so a file rename counts as a
  change even if the bytes are identical elsewhere.
* **Sort before hashing** to make the result order-independent: the same
  tree always produces the same digest, regardless of filesystem walk
  order on the host.
* **Follow symlinks = False**: a dangling symlink should be a no-op, not
  a crash. The target's contents, if reachable, belong to whichever tree
  actually owns it — not to us.
"""

from __future__ import annotations

import hashlib
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


_CHUNK = 1 << 20  # 1 MiB — small enough to keep memory flat, large enough to amortize syscalls


def _should_skip(rel: str, excludes: tuple[str, ...]) -> bool:
    """Glob-style exclude match against POSIX-style relative paths."""
    return any(fnmatch(rel, pat) for pat in excludes)


def hash_tree(
    root: Path,
    excludes: Iterable[str] = (),
) -> str:
    """Return a stable SHA-256 digest of every file under ``root``.

    ``excludes`` are glob patterns matched against the POSIX-style
    relative path. Directories are not hashed directly — only files, so
    empty directories don't affect the digest (consistent with how most
    backup tools treat them).

    Missing ``root`` raises :class:`FileNotFoundError`. A regular file
    passed as ``root`` is hashed as a single-entry tree.
    """
    if not root.exists():
        raise FileNotFoundError(root)

    ex = tuple(excludes)
    digest = hashlib.sha256()

    paths: list[tuple[str, Path]] = []
    if root.is_file():
        paths.append((root.name, root))
    else:
        root_resolved = root.resolve()
        for p in root.rglob("*"):
            if not p.is_file() or p.is_symlink():
                continue
            # A symlinked *directory* anywhere on the walk path is still
            # traversed by ``rglob`` (it only checks the final segment for
            # ``is_symlink``). Resolve the candidate and refuse anything
            # that escapes ``root`` — otherwise a ``source/mem -> ~/.ssh``
            # symlink silently pulls the target into the backup.
            try:
                if not p.resolve(strict=True).is_relative_to(root_resolved):
                    continue
            except OSError:
                continue
            rel_posix = p.relative_to(root).as_posix()
            if _should_skip(rel_posix, ex):
                continue
            paths.append((rel_posix, p))

    # Deterministic order — protects against filesystem-specific walk order.
    paths.sort(key=lambda t: t[0])

    for rel, fp in paths:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        try:
            with fp.open("rb") as fh:
                while chunk := fh.read(_CHUNK):
                    digest.update(chunk)
        except OSError:
            # Unreadable file — record its presence and path so the digest
            # still changes if the file later becomes readable, but don't
            # abort the whole backup over one permission problem.
            digest.update(b"<unreadable>")
        digest.update(b"\0")

    return digest.hexdigest()
