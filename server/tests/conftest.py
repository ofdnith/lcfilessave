from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from acervo import db
from acervo.config import Config


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(data_dir=tmp_path / "dados")


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "catalogo.db")
    db.migrate(c)
    yield c
    c.close()


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def insert_item(conn: sqlite3.Connection, sha: str = SHA_A, **overrides) -> int:
    values = {
        "sha256": sha,
        "kind": "photo",
        "size_bytes": 1000,
        "captured_at": "2024-05-01T10:12:00",
        "date_source": "exif",
        "source": "mac",
        "original_name": "IMG_1234.HEIC",
    }
    values.update(overrides)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO items ({cols}) VALUES ({marks})", tuple(values.values()))
    return cur.lastrowid


def insert_file(conn: sqlite3.Connection, item_id: int, sha: str = SHA_A, rel_path: str = "entrada/x.heic",
                role: str = "original") -> int:
    cur = conn.execute(
        "INSERT INTO files (item_id, role, sha256, size_bytes, ext, rel_path) VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, role, sha, 1000, "heic", rel_path),
    )
    return cur.lastrowid
