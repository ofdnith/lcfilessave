"""GET /api/health — is the server up, is the catalog usable, how full is the disk."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import __version__, db, media
from ..config import Config
from ..storage import disk_usage, missing_or_unwritable

router = APIRouter()


def _migration(cfg: Config) -> dict:
    try:
        conn = db.connect(cfg.db_path)
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = 'migration_active'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return {"active": False, "started_at": None}
    return {"active": row is not None, "started_at": row[0] if row else None}


@router.get("/api/health")
def health(request: Request) -> JSONResponse:
    cfg: Config = request.app.state.config
    problems: list[str] = []

    catalog = {"ok": False, "schema_version": None, "expected_version": db.latest_version()}
    try:
        conn = db.connect(cfg.db_path)
        try:
            conn.execute("SELECT 1 FROM items LIMIT 1").fetchall()
            catalog["schema_version"] = db.schema_version(conn)
            catalog["ok"] = catalog["schema_version"] == catalog["expected_version"]
        finally:
            conn.close()
    except (sqlite3.Error, db.MigrationError) as exc:
        problems.append(f"catálogo: {exc}")
    if not catalog["ok"] and not problems:
        problems.append("catálogo fora da versão esperada")

    problems.extend(missing_or_unwritable(cfg))

    usage = disk_usage(cfg.data_dir)
    storage = {
        "total_bytes": usage.total_bytes,
        "used_bytes": usage.used_bytes,
        "free_bytes": usage.free_bytes,
        "used_pct": usage.used_pct,
        "alert_pct": cfg.storage_alert_pct,
        "alert": usage.used_pct >= cfg.storage_alert_pct,
    }

    report = getattr(request.app.state, "reconcile_report", {}) or {}
    if report.get("missing"):
        problems.append(f"{report['missing']} arquivos do catálogo não foram encontrados no disco")

    ok = not problems
    gaz = getattr(request.app.state, "gazetteer", None)
    tools = {
        "exiftool": media.have("exiftool"),
        "ffmpeg": media.have("ffmpeg"),
        "heic": media.HEIF_OK,
        "pdf": media.have("pdftotext"),
        "ocr": media.have("tesseract"),
        "cities": bool(gaz and gaz.available),
    }
    body = {
        "status": "ok" if ok else "degraded",
        "version": __version__,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalog": catalog,
        "storage": storage,
        "tools": tools,
        "migration": _migration(cfg),
        "problems": problems,
    }
    return JSONResponse(body, status_code=200 if ok else 503)
