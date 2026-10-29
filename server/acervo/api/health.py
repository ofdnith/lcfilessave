"""GET /api/health — is the server up, is the catalog usable, how full is the disk."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import __version__, db
from ..config import Config
from ..storage import disk_usage, missing_or_unwritable

router = APIRouter()


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

    ok = not problems
    body = {
        "status": "ok" if ok else "degraded",
        "version": __version__,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalog": catalog,
        "storage": storage,
        "problems": problems,
    }
    return JSONResponse(body, status_code=200 if ok else 503)
