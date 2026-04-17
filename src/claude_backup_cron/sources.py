"""Materialize a source directory into a single tarball artefact.

Each source in the config becomes one tarball in the state directory per
run. The tarball name includes both the source ID and the content digest,
so repeated runs on unchanged content produce byte-identical files — a
property downstream destinations rely on to no-op.
"""

from __future__ import annotations

import tarfile
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from claude_backup_cron.errors import SourceError
from claude_backup_cron.hashing import hash_tree

if TYPE_CHECKING:
    from claude_backup_cron.config import SourceSpec


@dataclass(frozen=True, slots=True)
class Artefact:
    """A packaged source, ready to hand to a destination.

    ``digest`` is the content hash of the underlying tree (before
    tarring) — *not* the hash of the tarball. The same tree must always
    produce the same digest across runs, whereas a tar's mtime headers
    can drift.
    """

    source_id: str
    digest: str
    path: Path


def _filter_excluded(
    tarinfo: tarfile.TarInfo,
    excludes: tuple[str, ...],
    arcroot: str,
) -> tarfile.TarInfo | None:
    """tarfile filter: drop entries matching any ``excludes`` glob.

    ``tarinfo.name`` is the archive-internal path (prefixed with
    ``arcroot``); we strip that prefix before globbing so users can write
    patterns relative to the source root.
    """
    name = tarinfo.name
    if name == arcroot or name.startswith(arcroot + "/"):
        rel = name[len(arcroot) + 1 :] if len(name) > len(arcroot) else ""
    else:
        rel = name
    if rel and any(fnmatch(rel, pat) for pat in excludes):
        return None
    return tarinfo


def package(spec: SourceSpec, out_dir: Path) -> Artefact:
    """Tar ``spec.path`` into ``out_dir`` and return an :class:`Artefact`.

    The tarball is deterministic-ish: mtime on each entry is zeroed so
    two runs of the same content yield identical bytes (up to tarfile's
    own header quirks). ``out_dir`` is created if missing.
    """
    if not spec.path.exists():
        raise SourceError(f"source {spec.id!r}: path does not exist: {spec.path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hash_tree(spec.path, excludes=spec.exclude)
    artefact_path = out_dir / f"{spec.id}-{digest[:16]}.tar"
    arcroot = spec.id

    # If the exact same content was already packaged in this state dir,
    # reuse it rather than re-tarring.
    if artefact_path.exists():
        return Artefact(source_id=spec.id, digest=digest, path=artefact_path)

    tmp = artefact_path.with_suffix(".tar.tmp")
    try:
        with tarfile.open(tmp, "w") as tf:

            def _add_filter(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
                # Zero volatile metadata so identical content → identical bytes.
                ti.mtime = 0
                ti.uid = 0
                ti.gid = 0
                ti.uname = ""
                ti.gname = ""
                return _filter_excluded(ti, spec.exclude, arcroot)

            tf.add(str(spec.path), arcname=arcroot, filter=_add_filter)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SourceError(f"source {spec.id!r}: failed to tar: {exc}") from exc

    tmp.replace(artefact_path)
    return Artefact(source_id=spec.id, digest=digest, path=artefact_path)
