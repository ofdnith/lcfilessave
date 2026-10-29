"""Albums: named groups of items. Deleting an album never touches its items."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import auth, db
from ..catalog import ITEM_COLUMNS, ITEM_FROM, item_json, now_iso, transaction

router = APIRouter(prefix="/api/albums", dependencies=[Depends(auth.require_auth)])


def _conn(request: Request) -> sqlite3.Connection:
    return db.connect(request.app.state.config.db_path)


def album_json(conn: sqlite3.Connection, cfg, a: sqlite3.Row) -> dict:
    count = conn.execute(
        "SELECT count(*) FROM album_items ai JOIN items i ON i.id = ai.item_id "
        "WHERE ai.album_id = ? AND i.state IN ('inbox', 'library', 'archived')", (a["id"],)).fetchone()[0]
    cover = None
    cover_sql = (f"SELECT {ITEM_COLUMNS} FROM {ITEM_FROM} WHERE i.id = ? AND i.state IN ('inbox', 'library', 'archived')")
    if a["cover_item_id"]:
        cover = conn.execute(cover_sql, (a["cover_item_id"],)).fetchone()
    if cover is None:
        cover = conn.execute(
            f"SELECT {ITEM_COLUMNS} FROM {ITEM_FROM} JOIN album_items ai ON ai.item_id = i.id "
            f"WHERE ai.album_id = ? AND i.state IN ('inbox', 'library', 'archived') "
            f"ORDER BY i.important DESC, i.thumb_status = 'ok' DESC, i.captured_at DESC LIMIT 1", (a["id"],)).fetchone()
    return {"id": a["id"], "name": a["name"], "count": count, "cover": item_json(cover, cfg) if cover else None,
            "created_at": a["created_at"], "updated_at": a["updated_at"]}


def _album(conn: sqlite3.Connection, album_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Álbum não encontrado")
    return row


@router.get("")
def list_albums(request: Request) -> dict:
    cfg = request.app.state.config
    conn = _conn(request)
    try:
        return {"albums": [album_json(conn, cfg, a) for a in
                           conn.execute("SELECT * FROM albums ORDER BY updated_at DESC")]}
    finally:
        conn.close()


class NewAlbum(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.post("")
def create_album(body: NewAlbum, request: Request) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "Dê um nome ao álbum.")
    conn = _conn(request)
    try:
        aid = conn.execute("INSERT INTO albums (name) VALUES (?)", (body.name.strip(),)).lastrowid
        return album_json(conn, request.app.state.config, _album(conn, aid))
    finally:
        conn.close()


class AlbumPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    cover_item_id: int | None = None


@router.patch("/{album_id}")
def update_album(album_id: int, body: AlbumPatch, request: Request) -> dict:
    conn = _conn(request)
    try:
        _album(conn, album_id)
        with transaction(conn):
            if body.name is not None:
                if not body.name.strip():
                    raise HTTPException(400, "Dê um nome ao álbum.")
                conn.execute("UPDATE albums SET name = ?, updated_at = ? WHERE id = ?",
                             (body.name.strip(), now_iso(), album_id))
            if body.cover_item_id is not None:
                if not conn.execute("SELECT 1 FROM album_items WHERE album_id = ? AND item_id = ?",
                                    (album_id, body.cover_item_id)).fetchone():
                    raise HTTPException(400, "A capa precisa ser um item do álbum.")
                conn.execute("UPDATE albums SET cover_item_id = ?, updated_at = ? WHERE id = ?",
                             (body.cover_item_id, now_iso(), album_id))
        return album_json(conn, request.app.state.config, _album(conn, album_id))
    finally:
        conn.close()


@router.delete("/{album_id}")
def delete_album(album_id: int, request: Request) -> dict:
    conn = _conn(request)
    try:
        _album(conn, album_id)
        conn.execute("DELETE FROM albums WHERE id = ?", (album_id,))  # album_items cascade; items untouched
    finally:
        conn.close()
    return {"ok": True}


class Ids(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=5000)


@router.post("/{album_id}/items")
def add_items(album_id: int, body: Ids, request: Request) -> dict:
    conn = _conn(request)
    try:
        _album(conn, album_id)
        with transaction(conn):
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO album_items (album_id, item_id) SELECT ?, id FROM items "
                "WHERE id = ? AND state IN ('inbox', 'library', 'archived')", [(album_id, i) for i in body.ids])
            added = conn.total_changes - before
            conn.execute("UPDATE albums SET updated_at = ? WHERE id = ?", (now_iso(), album_id))
    finally:
        conn.close()
    return {"added": added}


@router.post("/{album_id}/items/remove")
def remove_items(album_id: int, body: Ids, request: Request) -> dict:
    conn = _conn(request)
    try:
        _album(conn, album_id)
        with transaction(conn):
            before = conn.total_changes
            conn.executemany("DELETE FROM album_items WHERE album_id = ? AND item_id = ?",
                             [(album_id, i) for i in body.ids])
            removed = conn.total_changes - before
            conn.execute("UPDATE albums SET updated_at = ?, cover_item_id = CASE WHEN cover_item_id IN "
                         f"({','.join('?' * len(body.ids))}) THEN NULL ELSE cover_item_id END WHERE id = ?",
                         (now_iso(), *body.ids, album_id))
    finally:
        conn.close()
    return {"removed": removed}
