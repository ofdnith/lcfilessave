"""What goes onto an external drive besides the originals:

  .acervo/catalogo.db   the items of this volume (standalone SQLite)
  .acervo/miniaturas/   thumbnails (copied by the Mac app)
  ABRIR-ACERVO.html     offline browser for the drive (rule 8): opens in any
                        browser, on any computer, without installing anything.
                        It also lists what is on the other drives.
"""

from __future__ import annotations

import html
import json
import sqlite3
from importlib import resources
from pathlib import Path

from .catalog import now_iso

VOLUME_ITEMS_SQL = """
    SELECT i.id, i.sha256, i.kind, i.original_name, i.standard_name, i.captured_at, i.captured_tz,
           i.size_bytes, i.width, i.height, i.duration_ms, i.place, i.gps_lat, i.gps_lon,
           trim(coalesce(i.camera_make, '') || ' ' || coalesce(i.camera_model, '')) AS camera,
           i.important, i.thumb_status,
           (SELECT vc.rel_path FROM files f JOIN volume_copies vc ON vc.file_id = f.id
             WHERE f.item_id = i.id AND f.role = 'original' AND vc.volume_id = :vid AND vc.verified_at IS NOT NULL) AS rel_path,
           (SELECT vc.rel_path FROM files f JOIN volume_copies vc ON vc.file_id = f.id
             WHERE f.item_id = i.id AND f.role = 'live-video' AND vc.volume_id = :vid AND vc.verified_at IS NOT NULL) AS live_rel_path
    FROM items i
    WHERE i.state <> 'purged' AND EXISTS (
        SELECT 1 FROM files f JOIN volume_copies vc ON vc.file_id = f.id
        WHERE f.item_id = i.id AND f.role = 'original' AND vc.volume_id = :vid AND vc.verified_at IS NOT NULL)
    ORDER BY i.captured_at DESC
"""


def volume_items(conn: sqlite3.Connection, volume_id: str) -> list[sqlite3.Row]:
    return conn.execute(VOLUME_ITEMS_SQL, {"vid": volume_id}).fetchall()


def build_volume_db(conn: sqlite3.Connection, volume: sqlite3.Row, dest: Path) -> None:
    dest.unlink(missing_ok=True)
    out = sqlite3.connect(dest)
    try:
        out.executescript("""
            CREATE TABLE volume (id TEXT, name TEXT, created_at TEXT, exported_at TEXT);
            CREATE TABLE items (id INTEGER PRIMARY KEY, sha256 TEXT, kind TEXT, original_name TEXT,
                standard_name TEXT, captured_at TEXT, captured_tz TEXT, size_bytes INTEGER, width INTEGER,
                height INTEGER, duration_ms INTEGER, place TEXT, gps_lat REAL, gps_lon REAL, camera TEXT,
                important INTEGER, rel_path TEXT, live_rel_path TEXT, thumbnail TEXT);
            CREATE TABLE files (item_id INTEGER, role TEXT, sha256 TEXT, size_bytes INTEGER, rel_path TEXT);
        """)
        out.execute("INSERT INTO volume VALUES (?, ?, ?, ?)",
                    (volume["id"], volume["name"], volume["created_at"], now_iso()))
        for r in volume_items(conn, volume["id"]):
            out.execute("INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                r["id"], r["sha256"], r["kind"], r["original_name"], r["standard_name"], r["captured_at"],
                r["captured_tz"], r["size_bytes"], r["width"], r["height"], r["duration_ms"], r["place"],
                r["gps_lat"], r["gps_lon"], r["camera"] or None, r["important"], r["rel_path"], r["live_rel_path"],
                f".acervo/miniaturas/{r['sha256']}.webp" if r["thumb_status"] == "ok" else None))
        out.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?)", conn.execute(
            "SELECT f.item_id, f.role, f.sha256, f.size_bytes, vc.rel_path FROM files f "
            "JOIN volume_copies vc ON vc.file_id = f.id WHERE vc.volume_id = ? AND vc.verified_at IS NOT NULL",
            (volume["id"],)).fetchall())
        out.commit()
    finally:
        out.close()


def build_open_html(conn: sqlite3.Connection, volume: sqlite3.Row) -> str:
    items = [[r["kind"], r["original_name"], r["captured_at"], r["rel_path"], r["live_rel_path"],
              r["sha256"] if r["thumb_status"] == "ok" else None, r["size_bytes"], r["place"], r["important"]]
             for r in volume_items(conn, volume["id"])]
    others = [[r["kind"], r["original_name"], r["captured_at"], r["vname"]] for r in conn.execute(
        "SELECT i.kind, i.original_name, i.captured_at, v.name AS vname FROM items i JOIN volumes v ON v.id = i.volume_id "
        "WHERE i.state = 'archived' AND i.volume_id <> ? ORDER BY i.captured_at DESC", (volume["id"],))]
    return render_open_html(volume["name"], items, others)


def render_open_html(name: str, items: list[list], others: list[list]) -> str:
    """The offline browser page (an HD or the microSD card). `items` rows:
    [kind, name, date, rel_path, live_rel_path, sha-if-thumbnail, bytes, place, important];
    `others`: [kind, name, date, volume name] — what lives on other drives."""
    data = {"volume": name, "exported_at": now_iso(), "items": items, "others": others}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = resources.files("acervo.static").joinpath("abrir-acervo.html").read_text("utf-8")
    return template.replace("/*__ACERVO_DATA__*/null", payload).replace("__VOLUME_NAME__", html.escape(name))
