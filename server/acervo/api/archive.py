"""External drives: volumes, verified transfer of a batch, drive bundle, health checks.

The server never sees the drive. The Mac app copies each file, re-reads it
FROM THE DRIVE, hashes it and reports the hash; the server records the copy as
verified only when that hash equals the catalog's. Only then can commit()
drop the server copy — and the database triggers refuse anything else.
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .. import auth, db, push
from ..catalog import drive_rel_path, log_event, now_iso, transaction
from ..volume_export import build_open_html, build_volume_db, volume_items

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_auth)])
_SAFE_REL = re.compile(r"^(?!/)(?!.*(^|/)\.\.(/|$))[^\x00]+$")


def _conn(request: Request) -> sqlite3.Connection:
    return db.connect(request.app.state.config.db_path)


def _volume(conn: sqlite3.Connection, volume_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM volumes WHERE id = ?", (volume_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Volume não encontrado")
    return row


def volume_json(conn: sqlite3.Connection, v: sqlite3.Row) -> dict:
    count = conn.execute(
        "SELECT count(DISTINCT f.item_id) FROM volume_copies vc JOIN files f ON f.id = vc.file_id "
        "WHERE vc.volume_id = ? AND vc.verified_at IS NOT NULL", (v["id"],)).fetchone()[0]
    last = conn.execute("SELECT kind, finished_at, files_checked, problems FROM volume_checks "
                        "WHERE volume_id = ? ORDER BY id DESC LIMIT 1", (v["id"],)).fetchone()
    return {"id": v["id"], "name": v["name"], "capacity_bytes": v["capacity_bytes"], "used_bytes": v["used_bytes"],
            "filesystem": v["filesystem"], "status": v["status"], "created_at": v["created_at"],
            "last_seen_at": v["last_seen_at"], "last_full_check_at": v["last_full_check_at"],
            "item_count": count, "last_check": dict(last) if last else None}


@router.get("/volumes")
def list_volumes(request: Request) -> dict:
    conn = _conn(request)
    try:
        vols = [volume_json(conn, v) for v in conn.execute("SELECT * FROM volumes ORDER BY name")]
    finally:
        conn.close()
    return {"volumes": vols, "archive_copies": request.app.state.config.archive_copies}


class NewVolume(BaseModel):
    capacity_bytes: int = Field(gt=0)
    filesystem: str = "exfat"
    id: str | None = None


@router.post("/volumes", dependencies=[Depends(auth.forbid_remote)])
def create_volume(body: NewVolume, request: Request) -> dict:
    if body.filesystem.lower() != "exfat":
        raise HTTPException(400, "O HD precisa estar formatado em exFAT.")
    vid = body.id or str(uuid.uuid4())
    try:
        uuid.UUID(vid)
    except ValueError:
        raise HTTPException(400, "id inválido") from None
    conn = _conn(request)
    try:
        with transaction(conn):
            existing = conn.execute("SELECT * FROM volumes WHERE id = ?", (vid,)).fetchone()
            if existing:
                return volume_json(conn, existing)
            last = conn.execute("SELECT max(CAST(substr(name, 8) AS INTEGER)) FROM volumes").fetchone()[0] or 0
            name = f"VOLUME-{last + 1:03d}"
            conn.execute("INSERT INTO volumes (id, name, capacity_bytes, filesystem, last_seen_at) VALUES (?, ?, ?, ?, ?)",
                         (vid, name, body.capacity_bytes, "exfat", now_iso()))
            log_event(conn, "mac-app", "volume-create", volume_id=vid, details={"name": name})
        return volume_json(conn, _volume(conn, vid))
    finally:
        conn.close()


class Seen(BaseModel):
    used_bytes: int | None = Field(None, ge=0)


@router.post("/volumes/{volume_id}/seen")
def volume_seen(volume_id: str, body: Seen, request: Request) -> dict:
    conn = _conn(request)
    try:
        _volume(conn, volume_id)
        conn.execute("UPDATE volumes SET last_seen_at = ?, used_bytes = coalesce(?, used_bytes) WHERE id = ?",
                     (now_iso(), body.used_bytes, volume_id))
        return volume_json(conn, _volume(conn, volume_id))
    finally:
        conn.close()


@router.get("/archive/plan")
def archive_plan(request: Request, volume_id: str, max_bytes: int | None = None) -> dict:
    cfg = request.app.state.config
    budget = max_bytes if max_bytes is not None else cfg.archive_batch_gb * 1_000_000_000
    conn = _conn(request)
    try:
        _volume(conn, volume_id)
        items = conn.execute(
            """SELECT i.id FROM items i
               WHERE i.state = 'library'
                 AND NOT EXISTS (SELECT 1 FROM files f WHERE f.item_id = i.id AND f.rel_path IS NULL)
               ORDER BY EXISTS (SELECT 1 FROM files f JOIN volume_copies vc ON vc.file_id = f.id
                                WHERE f.item_id = i.id AND vc.verified_at IS NOT NULL) DESC,
                        i.captured_at, i.id""").fetchall()
        plan, total = [], 0
        for it in items:
            files = conn.execute(
                "SELECT f.id, f.item_id, f.sha256, f.size_bytes, f.rel_path FROM files f WHERE f.item_id = ? "
                "AND NOT EXISTS (SELECT 1 FROM volume_copies vc WHERE vc.file_id = f.id AND vc.volume_id = ? "
                "AND vc.verified_at IS NOT NULL AND coalesce(vc.last_check_ok, 1) = 1)", (it["id"], volume_id)).fetchall()
            size = sum(f["size_bytes"] for f in files)
            if not files:
                continue
            if total + size > budget:
                if plan:
                    break
                continue  # a single item larger than the budget: skip it
            total += size
            plan += [{"file_id": f["id"], "item_id": f["item_id"], "sha256": f["sha256"],
                      "size_bytes": f["size_bytes"], "rel_path": drive_rel_path(f["rel_path"]),
                      "url": f"/api/files/{f['id']}/content"} for f in files]
    finally:
        conn.close()
    return {"files": plan, "total_bytes": total}


@router.get("/files/{file_id}/content")
def file_content(file_id: int, request: Request) -> FileResponse:
    cfg = request.app.state.config
    conn = _conn(request)
    try:
        row = conn.execute("SELECT rel_path, root, mime FROM files WHERE id = ?", (file_id,)).fetchone()
    finally:
        conn.close()
    if row is None or row["rel_path"] is None:
        raise HTTPException(404, "Arquivo não está no servidor")
    return FileResponse(cfg.root_dir(row["root"]) / row["rel_path"], media_type="application/octet-stream")


class Copy(BaseModel):
    file_id: int
    rel_path: str
    sha256: str


class Verified(BaseModel):
    volume_id: str
    copies: list[Copy] = Field(max_length=5000)


@router.post("/archive/verified", dependencies=[Depends(auth.forbid_remote)])
def archive_verified(body: Verified, request: Request) -> dict:
    accepted, rejected = [], []
    conn = _conn(request)
    try:
        _volume(conn, body.volume_id)
        with transaction(conn):
            for c in body.copies:
                f = conn.execute("SELECT id, item_id, sha256 FROM files WHERE id = ?", (c.file_id,)).fetchone()
                if f is None:
                    rejected.append({"file_id": c.file_id, "error": "arquivo desconhecido"})
                elif c.sha256.lower() != f["sha256"]:
                    rejected.append({"file_id": c.file_id, "error": "hash da cópia no HD não confere"})
                elif not _SAFE_REL.match(c.rel_path):
                    rejected.append({"file_id": c.file_id, "error": "caminho inválido"})
                else:
                    try:
                        conn.execute(
                            "INSERT INTO volume_copies (file_id, volume_id, rel_path, verified_at, last_check_at, last_check_ok) "
                            "VALUES (?, ?, ?, ?, ?, 1) ON CONFLICT(file_id, volume_id) DO UPDATE SET "
                            "rel_path = excluded.rel_path, verified_at = excluded.verified_at, "
                            "last_check_at = excluded.last_check_at, last_check_ok = 1",
                            (c.file_id, body.volume_id, c.rel_path, now_iso(), now_iso()))
                    except sqlite3.IntegrityError:
                        rejected.append({"file_id": c.file_id, "error": "outro arquivo já ocupa este caminho no HD"})
                        continue
                    log_event(conn, "mac-app", "archive-verify", item_id=f["item_id"], file_id=c.file_id,
                              volume_id=body.volume_id, sha256=f["sha256"], to_path=c.rel_path)
                    accepted.append(c.file_id)
    finally:
        conn.close()
    return {"accepted": accepted, "rejected": rejected}


class Commit(BaseModel):
    volume_id: str


_commit_lock = threading.Lock()

HEALTHY = "vc.verified_at IS NOT NULL AND coalesce(vc.last_check_ok, 1) = 1 AND hv.status <> 'problem'"


def _commit(cfg, volume_id: str) -> dict:
    """Archive every library item whose files all have enough HEALTHY verified drive
    copies (one of them on this volume), then drop the server copies."""
    archived, freed = 0, 0
    with _commit_lock:  # a retried request never runs alongside the first one
        conn = db.connect(cfg.db_path)
        try:
            _volume(conn, volume_id)
            ready_sql = f"""SELECT i.id FROM items i
                WHERE i.state = 'library' {{only}}
                  AND NOT EXISTS (
                      SELECT 1 FROM files f WHERE f.item_id = i.id AND (
                          f.rel_path IS NULL
                          OR NOT EXISTS (SELECT 1 FROM volume_copies vc JOIN volumes hv ON hv.id = vc.volume_id
                                         WHERE vc.file_id = f.id AND vc.volume_id = :vid AND {HEALTHY})
                          OR (SELECT count(DISTINCT vc.volume_id) FROM volume_copies vc
                              JOIN volumes hv ON hv.id = vc.volume_id
                              WHERE vc.file_id = f.id AND {HEALTHY}) < :copies))"""
            params = {"vid": volume_id, "copies": cfg.archive_copies}
            for it in conn.execute(ready_sql.format(only=""), params).fetchall():
                with transaction(conn):
                    # Re-check inside the write transaction: state may have changed meanwhile.
                    if not conn.execute(ready_sql.format(only="AND i.id = :iid"), {**params, "iid": it["id"]}).fetchone():
                        continue
                    files = conn.execute("SELECT id, sha256, rel_path, root, size_bytes FROM files WHERE item_id = ?",
                                         (it["id"],)).fetchall()
                    conn.execute("UPDATE items SET state = 'archived', volume_id = ? WHERE id = ?", (volume_id, it["id"]))
                    for f in files:
                        conn.execute("UPDATE files SET rel_path = NULL WHERE id = ?", (f["id"],))
                        log_event(conn, "mac-app", "archive-remove-server-copy", item_id=it["id"], file_id=f["id"],
                                  volume_id=volume_id, sha256=f["sha256"], from_path=f"{f['root']}:{f['rel_path']}")
                # After COMMIT. If we die before unlinking, reconcile() removes the
                # leftover: its hash belongs to a file with a healthy drive copy.
                archived += 1
                for f in files:
                    (cfg.root_dir(f["root"]) / f["rel_path"]).unlink(missing_ok=True)
                    freed += f["size_bytes"]
        finally:
            conn.close()
    return {"archived_items": archived, "freed_bytes": freed}


@router.post("/archive/commit", dependencies=[Depends(auth.forbid_remote)])
async def archive_commit(body: Commit, request: Request) -> dict:
    return await run_in_threadpool(_commit, request.app.state.config, body.volume_id)


@router.get("/volumes/{volume_id}/bundle")
def volume_bundle(volume_id: str, request: Request) -> dict:
    conn = _conn(request)
    try:
        _volume(conn, volume_id)
        thumbs = [{"path": f".acervo/miniaturas/{r['sha256']}.webp", "url": f"/api/items/{r['id']}/thumb"}
                  for r in volume_items(conn, volume_id) if r["thumb_status"] == "ok"]
    finally:
        conn.close()
    return {"files": [{"path": ".acervo/catalogo.db", "url": f"/api/volumes/{volume_id}/catalog.db"},
                      {"path": "ABRIR-ACERVO.html", "url": f"/api/volumes/{volume_id}/abrir.html"}, *thumbs]}


@router.get("/volumes/{volume_id}/catalog.db")
def volume_catalog(volume_id: str, request: Request) -> FileResponse:
    conn = _conn(request)
    try:
        vol = _volume(conn, volume_id)
        tmp = Path(tempfile.mkstemp(suffix=".db", dir=request.app.state.config.subdir("tmp"))[1])
        build_volume_db(conn, vol, tmp)
    finally:
        conn.close()
    return FileResponse(tmp, media_type="application/vnd.sqlite3", filename="catalogo.db",
                        background=BackgroundTask(tmp.unlink, missing_ok=True))


@router.get("/volumes/{volume_id}/abrir.html", response_class=HTMLResponse)
def volume_html(volume_id: str, request: Request) -> str:
    conn = _conn(request)
    try:
        return build_open_html(conn, _volume(conn, volume_id))
    finally:
        conn.close()


@router.get("/volumes/{volume_id}/sample")
def volume_sample(volume_id: str, request: Request, n: int = 50, full: int = 0) -> dict:
    conn = _conn(request)
    try:
        _volume(conn, volume_id)
        sql = ("SELECT vc.file_id, vc.rel_path, f.sha256 FROM volume_copies vc JOIN files f ON f.id = vc.file_id "
               "WHERE vc.volume_id = ? AND vc.verified_at IS NOT NULL ")
        rows = conn.execute(sql + ("ORDER BY vc.rel_path" if full else
                                   "ORDER BY coalesce(vc.last_check_at, '') , random() LIMIT ?"),
                            (volume_id,) if full else (volume_id, max(1, min(n, 2000)))).fetchall()
    finally:
        conn.close()
    return {"files": [dict(r) for r in rows]}


class Problem(BaseModel):
    file_id: int
    error: str


class Check(BaseModel):
    kind: str
    files_checked: int = Field(ge=0)
    problems: list[Problem] = []
    checked_file_ids: list[int] = []


@router.post("/volumes/{volume_id}/checks", dependencies=[Depends(auth.forbid_remote)])
def volume_check(volume_id: str, body: Check, request: Request) -> dict:
    if body.kind not in ("partial", "full"):
        raise HTTPException(400, "kind deve ser partial ou full")
    conn = _conn(request)
    try:
        _volume(conn, volume_id)
        now = now_iso()
        with transaction(conn):
            conn.execute("INSERT INTO volume_checks (volume_id, kind, started_at, finished_at, files_checked, problems) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (volume_id, body.kind, now, now, body.files_checked, len(body.problems)))
            bad = {p.file_id for p in body.problems}
            conn.executemany("UPDATE volume_copies SET last_check_at = ?, last_check_ok = ? WHERE volume_id = ? AND file_id = ?",
                             [(now, int(fid not in bad), volume_id, fid) for fid in {*body.checked_file_ids, *bad}])
            for p in body.problems:
                log_event(conn, "mac-app", "volume-problem", file_id=p.file_id, volume_id=volume_id,
                          details={"error": p.error[:300]})
            if bad:
                conn.execute("UPDATE volumes SET status = 'problem', last_seen_at = ? WHERE id = ?", (now, volume_id))
                vname = conn.execute("SELECT name FROM volumes WHERE id = ?", (volume_id,)).fetchone()[0]
                push.notify(request.app.state.config, "hd_problema", f"Problema no {vname}",
                            f"{len(bad)} arquivo(s) não conferem. Os originais continuam no servidor ou em outro HD; "
                            "faça uma verificação completa.", "/")
            elif body.kind == "full":
                conn.execute("UPDATE volumes SET last_full_check_at = ?, last_seen_at = ?, "
                             "status = CASE status WHEN 'problem' THEN 'active' ELSE status END WHERE id = ?",
                             (now, now, volume_id))
        return volume_json(conn, _volume(conn, volume_id))
    finally:
        conn.close()
