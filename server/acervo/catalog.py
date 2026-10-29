"""Catalog helpers shared by the API, the ingest pipeline and the workers:
timestamps, naming and paths, events, and the JSON shape of an item."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .config import LIBRARY_DIR, TRASH_DIR, Config

KIND_DIR = {"photo": "fotos", "video": "videos", "document": "docs", "audio": "audios", "other": "outros"}
_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def iso_in(days: float = 0, base: str | None = None) -> str:
    start = parse_iso(base) if base else datetime.now(timezone.utc)
    return (start + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def local_now() -> tuple[str, str]:
    dt = datetime.now().astimezone()
    off = dt.strftime("%z")
    return dt.strftime("%Y-%m-%dT%H:%M:%S"), f"{off[:3]}:{off[3:]}"


def ms_to_local(ms: int | float) -> tuple[str, str]:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone()
    off = dt.strftime("%z")
    return dt.strftime("%Y-%m-%dT%H:%M:%S"), f"{off[:3]}:{off[3:]}"


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE … COMMIT, ROLLBACK on any error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


# --- naming and paths -------------------------------------------------------------------

def safe_name(name: str) -> str:
    """A file name that is safe on ext4, exFAT and APFS; keeps the original as far as possible."""
    name = unicodedata.normalize("NFC", name.replace("\\", "/").rsplit("/", 1)[-1])
    name = _UNSAFE.sub("_", name).strip(" .")
    if not name:
        name = "arquivo"
    while len(name.encode()) > 180:  # exFAT limit is 255 UTF-16 chars; leave room for prefixes
        stem, dot, ext = name.rpartition(".")
        name = (stem[:-1] + dot + ext) if dot and len(stem) > 1 else name[:-1]
    return name


def standard_name(captured_at: str, original_name: str) -> str:
    """'2024-05-01T10:12:33' + 'IMG_1234.HEIC' -> '2024-05-01_1012_IMG_1234.HEIC'."""
    return f"{captured_at[:10]}_{captured_at[11:13]}{captured_at[14:16]}_{safe_name(original_name)}"


def library_dir(captured_at: str, kind: str) -> str:
    return f"{LIBRARY_DIR}/{captured_at[:4]}/{captured_at[5:7]}/{KIND_DIR[kind]}"


def drive_rel_path(server_rel_path: str) -> str:
    """Path on an external drive: same tree as the library, without the 'acervo/' prefix."""
    parts = server_rel_path.split("/")
    return "/".join(parts[1:]) if parts[0] in (LIBRARY_DIR, TRASH_DIR) else server_rel_path


def abs_path(cfg: Config, root: str, rel_path: str) -> Path:
    return cfg.root_dir(root) / rel_path


def free_rel_path(conn: sqlite3.Connection, cfg: Config, root: str, directory: str, name: str) -> str:
    """'dir/name' that is free on disk (in every root) and in the catalog; adds _2, _3…"""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 1
    while True:
        candidate = name if n == 1 else (f"{stem}_{n}.{ext}" if ext else f"{stem}_{n}")
        rel = f"{directory}/{candidate}"
        taken = conn.execute("SELECT 1 FROM files WHERE rel_path = ?", (rel,)).fetchone() or conn.execute(
            "SELECT 1 FROM volume_copies WHERE rel_path = ?", (drive_rel_path(rel),)).fetchone()
        on_disk = (cfg.root_dir(root) / rel).exists() or (
            cfg.sd_dir is not None and (cfg.sd_dir / rel).exists()) or (cfg.data_dir / rel).exists()
        if not taken and not on_disk:
            return rel
        n += 1


# --- events -----------------------------------------------------------------------------

def log_event(conn: sqlite3.Connection, actor: str, action: str, *, item_id: int | None = None,
              file_id: int | None = None, volume_id: str | None = None, sha256: str | None = None,
              from_path: str | None = None, to_path: str | None = None, details: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO events (actor, action, item_id, file_id, volume_id, sha256, from_path, to_path, details) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (actor, action, item_id, file_id, volume_id, sha256, from_path, to_path,
         json.dumps(details, ensure_ascii=False) if details else None),
    )


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, now_iso()),
    )


# --- JSON shape -------------------------------------------------------------------------

ITEM_COLUMNS = """
    i.id, i.sha256, i.kind, i.mime, i.size_bytes, i.original_name, i.standard_name,
    i.captured_at, i.captured_tz, i.date_source, i.uploaded_at, i.source, i.state, i.important,
    i.volume_id, v.name AS volume_name, i.width, i.height, i.duration_ms, i.gps_lat, i.gps_lon,
    i.place, i.camera_make, i.camera_model, i.is_live_photo, i.is_screenshot, i.origin_app,
    i.thumb_status, i.medium_status, i.trashed_at,
    (SELECT f.rel_path IS NOT NULL FROM files f WHERE f.item_id = i.id AND f.role = 'original') AS on_server,
    EXISTS (SELECT 1 FROM files f WHERE f.item_id = i.id AND f.role = 'live-video') AS has_live_video
"""
ITEM_FROM = "items i LEFT JOIN volumes v ON v.id = i.volume_id"


def item_json(row: sqlite3.Row, cfg: Config) -> dict:
    iid = row["id"]
    on_server = bool(row["on_server"])
    camera = " ".join(x for x in (row["camera_make"], row["camera_model"]) if x) or None
    if row["camera_make"] and row["camera_model"] and row["camera_model"].startswith(row["camera_make"]):
        camera = row["camera_model"]
    return {
        "id": iid,
        "sha256": row["sha256"],
        "kind": row["kind"],
        "mime": row["mime"],
        "size_bytes": row["size_bytes"],
        "original_name": row["original_name"],
        "standard_name": row["standard_name"],
        "captured_at": row["captured_at"],
        "captured_tz": row["captured_tz"],
        "date_uncertain": row["date_source"] == "upload",
        "uploaded_at": row["uploaded_at"],
        "source": row["source"],
        "state": row["state"],
        "important": bool(row["important"]),
        "volume": {"id": row["volume_id"], "name": row["volume_name"]} if row["volume_id"] else None,
        "width": row["width"],
        "height": row["height"],
        "duration_ms": row["duration_ms"],
        "gps": {"lat": row["gps_lat"], "lon": row["gps_lon"]} if row["gps_lat"] is not None else None,
        "place": row["place"],
        "camera": camera,
        "is_live_photo": bool(row["is_live_photo"]),
        "is_screenshot": bool(row["is_screenshot"]),
        "origin_app": row["origin_app"],
        "on_server": on_server,
        "thumb_url": f"/api/items/{iid}/thumb" if row["thumb_status"] == "ok" else None,
        "medium_url": f"/api/items/{iid}/medium" if row["medium_status"] == "ok" else None,
        "preview_url": f"/api/items/{iid}/preview" if on_server else None,
        "original_url": f"/api/items/{iid}/original" if on_server else None,
        "live_video_url": f"/api/items/{iid}/original?role=live-video" if on_server and row["has_live_video"] else None,
        "trashed_at": row["trashed_at"],
        "trash_expires_at": iso_in(cfg.trash_days, row["trashed_at"]) if row["trashed_at"] else None,
    }


def thumb_path(cfg: Config, sha256: str) -> Path:
    return cfg.subdir("miniaturas") / sha256[:2] / f"{sha256}.webp"


def medium_path(cfg: Config, sha256: str) -> Path:
    """Medium preview lives with the thumbnails: never deleted."""
    return cfg.subdir("miniaturas") / sha256[:2] / f"{sha256}-1024.webp"


def preview_path(cfg: Config, sha256: str) -> Path:
    return cfg.subdir("previas") / sha256[:2] / f"{sha256}.jpg"
