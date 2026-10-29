"""Data directory layout, disk usage and safe file operations.

Every function that moves or deletes bytes lives here, so the safety rules
(fsync, hash check before deleting a source) are implemented once.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import (
    GEO_DIR,
    INBOX_DIR,
    LIBRARY_DIR,
    PREVIEWS_DIR,
    THUMBS_DIR,
    TMP_DIR,
    TRASH_DIR,
    Config,
)

LAYOUT = (INBOX_DIR, LIBRARY_DIR, TRASH_DIR, THUMBS_DIR, TMP_DIR)
EXTRA_DIRS = (PREVIEWS_DIR, GEO_DIR, f"{TMP_DIR}/uploads")
CHUNK = 1024 * 1024
# Suffix of half-written copies. Unusual on purpose: an original may well be
# called "something.part", and must never be mistaken for a leftover.
TEMP_SUFFIX = ".acervo-tmp"


class DataDirBusy(RuntimeError):
    pass


def lock_data_dir(cfg: Config):
    """Exclusive lock on the data dir, held by the running server. Commands that
    rearrange files (acervo verificar/processar) refuse to run alongside it."""
    import fcntl
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    fh = open(cfg.data_dir / ".acervo.lock", "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        raise DataDirBusy("O servidor do Acervo está rodando nesta pasta. Pare-o antes (acervo-ctl stop).") from None
    return fh


def ensure_layout(cfg: Config) -> None:
    """Create the data dir and its subfolders. Never removes anything."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    for name in (*LAYOUT, *EXTRA_DIRS):
        cfg.subdir(name).mkdir(parents=True, exist_ok=True)
    if cfg.sd_dir is not None and cfg.sd_dir.is_dir():
        for name in (LIBRARY_DIR, TRASH_DIR):
            (cfg.sd_dir / name).mkdir(exist_ok=True)


def missing_or_unwritable(cfg: Config) -> list[str]:
    problems = []
    for path in (cfg.data_dir, *(cfg.subdir(n) for n in LAYOUT)):
        if not path.is_dir():
            problems.append(f"{path} não existe")
        elif not os.access(path, os.W_OK):
            problems.append(f"{path} sem permissão de escrita")
    if cfg.sd_dir is not None and not cfg.sd_dir.is_dir():
        problems.append(f"cartão microSD não encontrado em {cfg.sd_dir}")
    return problems


@dataclass(frozen=True)
class DiskUsage:
    total_bytes: int
    used_bytes: int
    free_bytes: int

    @property
    def used_pct(self) -> float:
        return round(100 * self.used_bytes / self.total_bytes, 1) if self.total_bytes else 0.0


def disk_usage(path: Path) -> DiskUsage:
    u = shutil.disk_usage(path)
    # "used" from statvfs leaves out blocks reserved for the system, so
    # used + free < total. What we can actually still write is `free`, so the
    # percentage is computed from it.
    return DiskUsage(total_bytes=u.total, used_bytes=u.total - u.free, free_bytes=u.free)


# --- hashing and safe moves ----------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def fsync_file(path: Path) -> None:
    with open(path, "rb+") as fh:
        os.fsync(fh.fileno())


class VerificationError(RuntimeError):
    pass


def move_verified(src: Path, dest: Path, expected_sha: str) -> None:
    """Move src to dest. Same filesystem: atomic rename. Different filesystem
    (e.g. internal storage -> microSD): copy, fsync, re-read and compare the
    SHA-256, and only then remove the source (inviolable rule 3)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dest)
        fsync_dir(dest.parent)
        return
    except OSError as exc:
        if exc.errno != 18:  # EXDEV: cross-device link
            raise
    part = dest.with_name(dest.name + TEMP_SUFFIX)
    with open(src, "rb") as fin, open(part, "wb") as fout:
        shutil.copyfileobj(fin, fout, CHUNK)
        fout.flush()
        os.fsync(fout.fileno())
    if sha256_file(part) != expected_sha:
        part.unlink(missing_ok=True)
        raise VerificationError(f"cópia de {src.name} não confere; origem mantida")
    os.replace(part, dest)
    fsync_dir(dest.parent)
    src.unlink()
    fsync_dir(src.parent)


def unique_name(directory: Path, name: str, taken: set[str] | None = None) -> str:
    """'x.jpg' -> 'x.jpg', 'x_2.jpg', 'x_3.jpg'… avoiding files on disk and `taken`."""
    taken = taken or set()
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    candidate, n = name, 1
    while (directory / candidate).exists() or candidate in taken:
        n += 1
        candidate = f"{stem}_{n}.{ext}" if ext else f"{stem}_{n}"
    return candidate
