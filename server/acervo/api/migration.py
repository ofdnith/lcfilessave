"""/api/migration/* — the OLD server's side of `acervo migrar`.

Once started, the old server is frozen ("só consulta"): every request that
would change data answers 423 and background jobs pause, so the catalog copy
and the files the new server downloads stay consistent. The old server never
deletes anything; the owner switches it off after checking the new one.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .. import auth, db
from ..catalog import get_setting, log_event, now_iso, set_setting, transaction
from ..config import CERTS_DIR, GEO_DIR, THUMBS_DIR
from ..storage import sha256_file

# Only a short-lived migration token, and only from the home network.
router = APIRouter(prefix="/api/migration",
                   dependencies=[Depends(auth.forbid_remote), Depends(auth.require_migration_token)])
DRAIN_TIMEOUT_S = 300
AUX_DIRS = (THUMBS_DIR, CERTS_DIR, GEO_DIR)


def migration_state(cfg) -> dict:
    conn = db.connect(cfg.db_path)
    try:
        started = get_setting(conn, "migration_active")
    finally:
        conn.close()
    return {"active": bool(started), "started_at": started or None}


def catalog_marker(conn: sqlite3.Connection) -> str:
    """Changes whenever anything is added, moved or deleted: compared at the end of
    the migration to prove the old server did not change while it was copied."""
    r = conn.execute(
        "SELECT (SELECT coalesce(max(id), 0) FROM events), (SELECT count(*) FROM files), "
        "(SELECT count(*) FROM files WHERE rel_path IS NOT NULL), (SELECT coalesce(max(updated_at), '') FROM items), "
        "(SELECT count(*) FROM items)").fetchone()
    return "|".join(str(x) for x in r)


@router.post("/start")
async def start(request: Request) -> dict:
    """Freeze, then wait until nothing is still writing (an upload being hashed, a
    keep being moved, a background job), then tidy disk and catalog so the copy
    is complete. Runs on the event loop, like the write guard, so a request is
    either refused or counted — never in between."""
    cfg = request.app.state.config
    state = request.app.state
    first = not migration_state(cfg)["active"]
    if first:
        conn = db.connect(cfg.db_path)
        try:
            with transaction(conn):
                set_setting(conn, "migration_active", now_iso())
                log_event(conn, "migration", "migration-start")
        finally:
            conn.close()
    state.migration_active = True

    waited = 0.0
    worker = getattr(state, "worker", None)
    while state.inflight_writes > 0 or (worker is not None and worker.busy):
        if waited >= DRAIN_TIMEOUT_S:
            raise HTTPException(409, "Ainda há envios ou tarefas terminando no servidor antigo. "
                                     "Espere alguns minutos e rode o migrar de novo.")
        await asyncio.sleep(0.2)
        waited += 0.2

    if first:
        # Files on disk that the catalog does not know yet (left by an old crash) are
        # cataloged now, so they are part of the copy instead of staying behind.
        from ..ingest import reconcile
        await run_in_threadpool(reconcile, cfg, state.ingestor)
    conn = db.connect(cfg.db_path)
    try:
        marker = catalog_marker(conn)
    finally:
        conn.close()
    return {**migration_state(cfg), "marker": marker}


@router.get("/marker")
def marker(request: Request) -> dict:
    _require_active(request)
    conn = db.connect(request.app.state.config.db_path)
    try:
        return {"marker": catalog_marker(conn)}
    finally:
        conn.close()


@router.post("/cancel")
def cancel(request: Request) -> dict:
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        with transaction(conn):
            conn.execute("DELETE FROM settings WHERE key = 'migration_active'")
            log_event(conn, "migration", "migration-cancel")
    finally:
        conn.close()
    request.app.state.migration_active = False
    return {"active": False, "started_at": None}


def _require_active(request: Request) -> None:
    if not migration_state(request.app.state.config)["active"]:
        raise HTTPException(409, "Comece a migração antes (POST /api/migration/start).")


@router.get("/catalog")
def catalog(request: Request) -> FileResponse:
    _require_active(request)
    cfg = request.app.state.config
    fd, tmp_name = tempfile.mkstemp(suffix=".db", dir=cfg.subdir("tmp"))
    os.close(fd)
    tmp = Path(tmp_name)
    conn = db.connect(cfg.db_path)
    try:
        target = sqlite3.connect(tmp)
        try:
            conn.backup(target)  # consistent snapshot, even with WAL
        finally:
            target.close()
    finally:
        conn.close()
    conn = db.connect(cfg.db_path)
    try:
        mark = catalog_marker(conn)
    finally:
        conn.close()
    return FileResponse(tmp, media_type="application/vnd.sqlite3", filename="catalogo.db",
                        headers={"X-Acervo-SHA256": sha256_file(tmp), "X-Acervo-Marker": mark},
                        background=BackgroundTask(tmp.unlink, missing_ok=True))


@router.get("/manifest")
def manifest(request: Request) -> dict:
    _require_active(request)
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        files = [{"kind": "original", "root": r["root"], "path": r["rel_path"], "size": r["size_bytes"],
                  "sha256": r["sha256"]}
                 for r in conn.execute("SELECT root, rel_path, size_bytes, sha256 FROM files "
                                       "WHERE rel_path IS NOT NULL ORDER BY id")]
    finally:
        conn.close()
    for top in AUX_DIRS:
        base = cfg.subdir(top)
        if not base.is_dir():
            continue
        for dirpath, _dirs, names in os.walk(base):
            for name in names:
                if name.endswith((".tmp", ".part")):
                    continue
                p = Path(dirpath) / name
                files.append({"kind": "aux", "root": "main", "path": p.relative_to(cfg.data_dir).as_posix(),
                              "size": p.stat().st_size, "sha256": None})
    return {"files": files, "total_bytes": sum(f["size"] for f in files)}


@router.get("/file")
def file(request: Request, kind: str, path: str, root: str = "main") -> Response:
    _require_active(request)
    cfg = request.app.state.config
    if kind == "original":
        conn = db.connect(cfg.db_path)
        try:
            row = conn.execute("SELECT 1 FROM files WHERE rel_path = ? AND root = ?", (path, root)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise HTTPException(404, "Arquivo fora do manifesto")
        full = cfg.root_dir(root) / path
        if not full.is_file():
            raise HTTPException(404, "Arquivo sumiu do disco do servidor antigo")
        return FileResponse(full, media_type="application/octet-stream")
    if kind == "aux":
        full = (cfg.data_dir / path).resolve()
        allowed = [cfg.subdir(d).resolve() for d in AUX_DIRS]
        if not any(a in full.parents for a in allowed) or not full.is_file():
            raise HTTPException(404, "Arquivo fora do manifesto")
        data = full.read_bytes()  # small files (thumbnails, certificates, city list)
        return Response(data, media_type="application/octet-stream",
                        headers={"X-Acervo-SHA256": hashlib.sha256(data).hexdigest()})
    raise HTTPException(400, "kind inválido")
