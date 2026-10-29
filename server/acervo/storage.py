"""Data directory layout and disk usage."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import INBOX_DIR, LIBRARY_DIR, THUMBS_DIR, TMP_DIR, TRASH_DIR, Config

LAYOUT = (INBOX_DIR, LIBRARY_DIR, TRASH_DIR, THUMBS_DIR, TMP_DIR)


def ensure_layout(cfg: Config) -> None:
    """Create the data dir and its subfolders. Never removes anything."""
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    for name in LAYOUT:
        cfg.subdir(name).mkdir(exist_ok=True)


def missing_or_unwritable(cfg: Config) -> list[str]:
    problems = []
    for path in (cfg.data_dir, *(cfg.subdir(n) for n in LAYOUT)):
        if not path.is_dir():
            problems.append(f"{path} não existe")
        elif not os.access(path, os.W_OK):
            problems.append(f"{path} sem permissão de escrita")
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
