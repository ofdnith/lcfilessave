"""Sending files: sessions, pre-check (dedup layers 1-2), tus resumable upload,
and a simple single-request upload for iPhone Shortcuts and the Mac app."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.concurrency import run_in_threadpool

from .. import auth, db, media
from ..catalog import now_iso, set_setting, transaction
from ..ingest import count_in_session, fingerprint_time, normalize_client_time
from ..storage import disk_usage

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_auth)])

SOURCES = ("iphone-daily", "iphone-manual", "iphone-empty", "mac", "web", "webdav")
TUS_HEADERS = {"Tus-Resumable": "1.0.0"}
SPACE_MARGIN = 1_000_000_000
_patch_locks: dict[str, asyncio.Lock] = {}


def _conn(request: Request) -> sqlite3.Connection:
    return db.connect(request.app.state.config.db_path)


def _uploads_dir(request: Request) -> Path:
    return request.app.state.config.subdir("tmp") / "uploads"


def _check_space(request: Request, length: int) -> None:
    if disk_usage(request.app.state.config.data_dir).free_bytes < length + SPACE_MARGIN:
        raise HTTPException(507, "Sem espaço no servidor. Transfira um lote para um HD.")


# --- sessions ------------------------------------------------------------------------------

def _plural(n: int, one: str, many: str) -> str:
    return f"{n:,}".replace(",", ".") + " " + (one if n == 1 else many)


def session_json(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    data = {k: row[k] for k in ("id", "source", "status", "expected_count", "received_verified_count",
                                "new_count", "existing_count", "near_dup_count", "failed_count",
                                "started_at", "finished_at", "bytes_received")}
    if row["source"] == "iphone-daily":
        kinds = dict(conn.execute(
            "SELECT i.kind, count(*) FROM session_files sf JOIN files f ON f.sha256 = sf.sha256 "
            "JOIN items i ON i.id = f.item_id WHERE sf.session_id = ? AND sf.outcome = 'new' "
            "AND f.role = 'original' GROUP BY i.kind", (row["id"],)).fetchall())
        parts = [_plural(kinds.get("photo", 0), "foto", "fotos"), _plural(kinds.get("video", 0), "vídeo", "vídeos")]
        others = sum(v for k, v in kinds.items() if k not in ("photo", "video"))
        if others:
            parts.append(_plural(others, "outro", "outros"))
        data["summary_text"] = "Backup diário: " + (", ".join(parts) if kinds else "nada novo")
    else:
        data["summary_text"] = " · ".join([
            _plural(row["new_count"], "novo", "novos"),
            _plural(row["existing_count"], "já existia", "já existiam"),
            _plural(row["near_dup_count"], "quase-duplicado para revisar", "quase-duplicados para revisar"),
        ])
    data["safe_to_delete"] = bool(row["expected_count"]) and row["received_verified_count"] >= row["expected_count"]
    return data


class SessionBody(BaseModel):
    source: str
    expected_count: int | None = Field(None, ge=0)
    client_label: str | None = None


def _session(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM upload_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Sessão não encontrada")
    return row


@router.post("/sessions")
def create_session(body: SessionBody, request: Request) -> dict:
    if body.source not in SOURCES:
        raise HTTPException(400, f"source deve ser um de: {', '.join(SOURCES)}")
    conn = _conn(request)
    try:
        sid = conn.execute("INSERT INTO upload_sessions (source, expected_count, client_label) VALUES (?, ?, ?)",
                           (body.source, body.expected_count, body.client_label)).lastrowid
        return session_json(conn, _session(conn, sid))
    finally:
        conn.close()


@router.get("/sessions/{session_id}")
def get_session(session_id: int, request: Request) -> dict:
    conn = _conn(request)
    try:
        return session_json(conn, _session(conn, session_id))
    finally:
        conn.close()


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: int, request: Request) -> dict:
    conn = _conn(request)
    try:
        row = _session(conn, session_id)
        with transaction(conn):
            if row["status"] == "open":
                conn.execute("UPDATE upload_sessions SET status = 'finished', finished_at = ? WHERE id = ?",
                             (now_iso(), session_id))
            if row["source"] == "iphone-daily":
                set_setting(conn, "last_daily_backup_at", now_iso())
        return session_json(conn, _session(conn, session_id))
    finally:
        conn.close()


# --- pre-check -------------------------------------------------------------------------------

class PrecheckEntry(BaseModel):
    key: str
    name: str | None = None
    created_at: str | int | None = None
    size: int | None = None
    sha256: str | None = None


class PrecheckBody(BaseModel):
    session_id: int | None = None
    entries: list[PrecheckEntry] = Field(max_length=5000)


@router.post("/precheck")
def precheck(body: PrecheckBody, request: Request) -> dict:
    conn = _conn(request)
    results = []
    try:
        with transaction(conn):
            for e in body.entries:
                res = {"key": e.key, "known": False, "by": None, "state": None, "item_id": None, "verified": False}
                if e.sha256:
                    row = conn.execute(
                        "SELECT i.id, i.state, f.size_bytes FROM files f JOIN items i ON i.id = f.item_id "
                        "WHERE f.sha256 = ?", (e.sha256.lower(),)).fetchone()
                    if row:
                        res.update(known=True, by="hash", state=row["state"], item_id=row["id"], verified=True)
                        count_in_session(conn, body.session_id, e.sha256.lower(), "existing", 0, e.key)
                        if body.session_id:
                            conn.execute("INSERT INTO dedupe_hits (session_id, item_id, layer, original_name) "
                                         "VALUES (?, ?, 2, ?)", (body.session_id, row["id"], e.name))
                elif e.name and e.size is not None and e.created_at is not None:
                    stamp = fingerprint_time(normalize_client_time(e.created_at))
                    row = conn.execute(
                        "SELECT i.id, i.state FROM fingerprints fp JOIN items i ON i.id = fp.item_id "
                        "WHERE fp.original_name = ? AND fp.client_created_at = ? AND fp.size_bytes = ?",
                        (e.name, stamp, e.size)).fetchone() if stamp else None
                    if row:
                        res.update(known=True, by="fingerprint", state=row["state"], item_id=row["id"])
                        if body.session_id:
                            conn.execute("INSERT INTO dedupe_hits (session_id, item_id, layer, original_name) "
                                         "VALUES (?, ?, 1, ?)", (body.session_id, row["id"], e.name))
                results.append(res)
    finally:
        conn.close()
    return {"results": results}


# --- ingest helper ---------------------------------------------------------------------------

async def _ingest(request: Request, path: Path, *, filename: str, source: str, session_id: int | None,
                  client_modified: object, client_sha: str | None, client_key: str | None) -> dict:
    state = request.app.state
    try:
        result = await run_in_threadpool(
            state.ingestor.ingest, path, filename=filename, source=source, session_id=session_id,
            client_modified=client_modified, client_sha=client_sha, actor=source, client_key=client_key)
    finally:
        if getattr(state, "worker", None):
            state.worker.wake()
    return result


def _validate_source(source: str | None) -> str:
    source = source or "web"
    if source not in SOURCES:
        raise HTTPException(400, "source inválido")
    return source


# --- tus 1.0.0 -------------------------------------------------------------------------------

def _parse_metadata(header: str) -> dict[str, str]:
    meta = {}
    for pair in filter(None, (p.strip() for p in header.split(","))):
        key, _, value = pair.partition(" ")
        try:
            meta[key] = base64.b64decode(value).decode("utf-8") if value else ""
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, f"Upload-Metadata inválido em '{key}'") from None
    return meta


@router.options("/uploads")
def tus_options() -> Response:
    return Response(status_code=204, headers={**TUS_HEADERS, "Tus-Version": "1.0.0",
                                              "Tus-Extension": "creation,termination"})


@router.post("/uploads")
def tus_create(request: Request) -> Response:
    try:
        length = int(request.headers["upload-length"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Upload-Length obrigatório") from None
    if length < 0:
        raise HTTPException(400, "Upload-Length inválido")
    meta = _parse_metadata(request.headers.get("upload-metadata", ""))
    filename = meta.get("filename") or meta.get("name")
    if not filename:
        raise HTTPException(400, "metadata 'filename' obrigatório")
    _check_space(request, length)
    source = _validate_source(meta.get("source"))
    session_id = int(meta["session_id"]) if meta.get("session_id", "").isdigit() else None
    sha = (meta.get("sha256") or "").lower() or None
    upload_id = secrets.token_hex(16)
    _uploads_dir(request).mkdir(parents=True, exist_ok=True)
    (_uploads_dir(request) / f"{upload_id}.part").touch()
    conn = _conn(request)
    try:
        conn.execute(
            "INSERT INTO uploads (id, length, filename, mime, client_modified, client_sha256, source, session_id, result) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (upload_id, length, filename, meta.get("filetype"), meta.get("lastModified"),
             sha if sha and len(sha) == 64 else None, source,
             session_id if session_id and conn.execute("SELECT 1 FROM upload_sessions WHERE id = ?", (session_id,)).fetchone() else None,
             json.dumps({"client_key": meta.get("client_key")}) if meta.get("client_key") else None))
    finally:
        conn.close()
    return Response(status_code=201, headers={**TUS_HEADERS, "Location": f"/api/uploads/{upload_id}"})


def _upload(conn: sqlite3.Connection, upload_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    if row is None or row["status"] == "cancelled":
        raise HTTPException(404, "Upload não encontrado", headers=TUS_HEADERS)
    return row


def _offset(request: Request, row: sqlite3.Row) -> int:
    if row["status"] in ("done", "processing"):
        return row["length"]
    part = _uploads_dir(request) / f"{row['id']}.part"
    return part.stat().st_size if part.exists() else 0


@router.head("/uploads/{upload_id}")
def tus_head(upload_id: str, request: Request) -> Response:
    conn = _conn(request)
    try:
        row = _upload(conn, upload_id)
    finally:
        conn.close()
    if row["status"] == "failed":
        raise HTTPException(404, "Upload falhou; envie de novo", headers=TUS_HEADERS)
    return Response(status_code=200, headers={**TUS_HEADERS, "Upload-Offset": str(_offset(request, row)),
                                              "Upload-Length": str(row["length"]), "Cache-Control": "no-store"})


@router.patch("/uploads/{upload_id}")
async def tus_patch(upload_id: str, request: Request) -> Response:
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/offset+octet-stream":
        raise HTTPException(415, "Content-Type deve ser application/offset+octet-stream", headers=TUS_HEADERS)
    try:
        client_offset = int(request.headers["upload-offset"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Upload-Offset obrigatório", headers=TUS_HEADERS) from None

    lock = _patch_locks.setdefault(upload_id, asyncio.Lock())
    async with lock:
        conn = _conn(request)
        try:
            row = _upload(conn, upload_id)
        finally:
            conn.close()
        offset = _offset(request, row)
        if client_offset != offset:
            raise HTTPException(409, "Upload-Offset não confere", headers={**TUS_HEADERS, "Upload-Offset": str(offset)})
        if row["status"] in ("done", "processing"):
            return Response(status_code=204, headers={**TUS_HEADERS, "Upload-Offset": str(offset)})

        part = _uploads_dir(request) / f"{upload_id}.part"
        remaining = row["length"] - offset
        fh = await run_in_threadpool(open, part, "ab")
        try:
            async for chunk in request.stream():
                if not chunk:
                    continue
                if len(chunk) > remaining:
                    raise HTTPException(400, "Mais dados que Upload-Length", headers=TUS_HEADERS)
                await run_in_threadpool(fh.write, chunk)
                remaining -= len(chunk)
            await run_in_threadpool(fh.flush)
            await run_in_threadpool(os.fsync, fh.fileno())
        except OSError as exc:
            raise HTTPException(507 if exc.errno == 28 else 500, "Falha ao gravar no servidor", headers=TUS_HEADERS) from None
        finally:
            await run_in_threadpool(fh.close)
        offset = row["length"] - remaining

        if remaining == 0:
            await _finish_tus(request, row, part)
        else:
            conn = _conn(request)
            try:
                conn.execute("UPDATE uploads SET updated_at = ? WHERE id = ?", (now_iso(), upload_id))
            finally:
                conn.close()
    _patch_locks.pop(upload_id, None)
    return Response(status_code=204, headers={**TUS_HEADERS, "Upload-Offset": str(offset)})


async def _finish_tus(request: Request, row: sqlite3.Row, part: Path) -> None:
    conn = _conn(request)
    try:
        conn.execute("UPDATE uploads SET status = 'processing', updated_at = ? WHERE id = ?", (now_iso(), row["id"]))
    finally:
        conn.close()
    extra = json.loads(row["result"]) if row["result"] else {}
    try:
        result = await _ingest(request, part, filename=row["filename"], source=row["source"],
                               session_id=row["session_id"], client_modified=row["client_modified"],
                               client_sha=row["client_sha256"], client_key=extra.get("client_key"))
    except Exception as exc:
        part.unlink(missing_ok=True)  # the client starts this file again from zero
        result = {"status": "failed", "item_id": None, "message": f"Erro ao processar: {exc}"}
    conn = _conn(request)
    try:
        conn.execute("UPDATE uploads SET status = ?, result = ?, updated_at = ? WHERE id = ?",
                     ("failed" if result["status"] == "failed" else "done", json.dumps(result, ensure_ascii=False),
                      now_iso(), row["id"]))
    finally:
        conn.close()


@router.delete("/uploads/{upload_id}")
def tus_delete(upload_id: str, request: Request) -> Response:
    conn = _conn(request)
    try:
        row = _upload(conn, upload_id)
        if row["status"] == "receiving":
            conn.execute("UPDATE uploads SET status = 'cancelled', updated_at = ? WHERE id = ?", (now_iso(), upload_id))
            (_uploads_dir(request) / f"{upload_id}.part").unlink(missing_ok=True)
    finally:
        conn.close()
    return Response(status_code=204, headers=TUS_HEADERS)


@router.get("/uploads/{upload_id}/result")
def tus_result(upload_id: str, request: Request) -> dict:
    conn = _conn(request)
    try:
        row = conn.execute("SELECT status, result FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "Upload não encontrado")
    if row["status"] in ("receiving", "processing"):
        return {"status": row["status"], "item_id": None, "message": "Ainda recebendo" if row["status"] == "receiving" else "Processando"}
    result = json.loads(row["result"] or "{}")
    result.pop("client_key", None)
    return result


# --- simple upload ---------------------------------------------------------------------------

class _FormStream:
    """Streams a multipart body straight to disk: big videos from the iPhone are
    never held in memory nor written twice."""

    def __init__(self, dest: Path, boundary: bytes) -> None:
        self.dest = dest
        self.fields: dict[str, str] = {}
        self.filename: str | None = None
        self._fh = None
        self._headers: dict[str, str] = {}
        self._field = b""
        self._value = b""
        self._name: str | None = None
        self._buf = bytearray()
        self.parser = MultipartParser(boundary, callbacks={
            "on_part_begin": self._begin, "on_part_data": self._data, "on_part_end": self._end,
            "on_header_field": self._hfield, "on_header_value": self._hvalue,
            "on_header_end": self._hend, "on_headers_finished": self._hdone,
        })

    def _begin(self):
        self._headers, self._name, self._buf = {}, None, bytearray()

    def _hfield(self, data, start, end):
        self._field += data[start:end]

    def _hvalue(self, data, start, end):
        self._value += data[start:end]

    def _hend(self):
        self._headers[self._field.decode("latin-1").lower()] = self._value.decode("utf-8", "replace")
        self._field, self._value = b"", b""

    def _hdone(self):
        _, params = parse_options_header(self._headers.get("content-disposition", ""))
        self._name = params.get(b"name", b"").decode("utf-8", "replace")
        fname = params.get(b"filename")
        if self._name == "file" or (fname is not None and self._fh is None):
            self.filename = (fname or b"arquivo").decode("utf-8", "replace")
            self._name = "file"
            self._fh = open(self.dest, "wb")

    def _data(self, data, start, end):
        if self._name == "file" and self._fh:
            self._fh.write(data[start:end])
        elif len(self._buf) < 10_000:
            self._buf += data[start:end]

    def _end(self):
        if self._name != "file" and self._name:
            self.fields[self._name] = self._buf.decode("utf-8", "replace")

    def close(self):
        if self._fh:
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()


@router.post("/upload")
async def simple_upload(request: Request) -> dict:
    length = int(request.headers.get("content-length") or 0)
    _check_space(request, length)
    params = dict(request.query_params)
    dest = _uploads_dir(request) / f"simple-{secrets.token_hex(12)}.part"
    dest.parent.mkdir(parents=True, exist_ok=True)
    ctype, opts = parse_options_header(request.headers.get("content-type", ""))
    try:
        if ctype == b"multipart/form-data":
            boundary = opts.get(b"boundary")
            if not boundary:
                raise HTTPException(400, "multipart sem boundary")
            form = _FormStream(dest, boundary)
            try:
                async for chunk in request.stream():
                    await run_in_threadpool(form.parser.write, chunk)
                form.parser.finalize()
            finally:
                form.close()
            if form.filename is None:
                raise HTTPException(400, "Campo 'file' ausente")
            params = {**form.fields, **params}
            filename = params.get("filename") or form.filename
        else:
            raw_name = request.headers.get("x-filename")
            if not raw_name:
                raise HTTPException(400, "Envie multipart com o campo 'file' ou o cabeçalho X-Filename")
            filename = unquote(raw_name)
            fh = await run_in_threadpool(open, dest, "wb")
            try:
                async for chunk in request.stream():
                    await run_in_threadpool(fh.write, chunk)
                await run_in_threadpool(fh.flush)
                await run_in_threadpool(os.fsync, fh.fileno())
            finally:
                await run_in_threadpool(fh.close)
        source = _validate_source(params.get("source"))
        session_id = int(params["session_id"]) if str(params.get("session_id", "")).isdigit() else None
        sha = (params.get("sha256") or "").lower() or None
        if not dest.exists() or (dest.stat().st_size == 0 and media.kind_of(filename) != "document"):
            raise HTTPException(400, "Arquivo vazio")
        return await _ingest(request, dest, filename=filename, source=source, session_id=session_id,
                             client_modified=params.get("created_at"), client_sha=sha,
                             client_key=params.get("client_key"))
    finally:
        dest.unlink(missing_ok=True)  # ingest moved it away; anything left is a failed request
