"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from . import __version__, db, media
from .api import albums, archive, auth as auth_api, health, items, migration, push as push_api, uploads
from .config import CERTS_DIR, GEO_DIR, Config, load_config
from .ingest import Ingestor, reconcile
from .jobs import Worker
from .places import Gazetteer
from .api.uploads import recover_uploads
from .storage import ensure_layout, lock_data_dir

log = logging.getLogger(__name__)


def prepare(cfg: Config) -> tuple[int, int]:
    """Create folders and bring the catalog up to date. Safe to run many times."""
    ensure_layout(cfg)
    conn = db.connect(cfg.db_path)
    try:
        before, after = db.migrate(conn, backup_dir=cfg.data_dir)
    finally:
        conn.close()
    if before != after:
        log.info("Catálogo migrado da versão %s para %s", before, after)
    return before, after


def create_app(cfg: Config) -> FastAPI:
    exiftool = media.ExifTool()
    gazetteer = Gazetteer(cfg.subdir(GEO_DIR))
    ingestor = Ingestor(cfg, exiftool)
    worker = Worker(cfg, exiftool, gazetteer)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        lock = lock_data_dir(cfg)
        prepare(cfg)
        report = reconcile(cfg, ingestor)
        report["uploads_recovered"] = recover_uploads(cfg, ingestor)
        app.state.reconcile_report = report
        if cfg.workers:
            worker.start()
        log.info("Acervo %s pronto · dados em %s · exiftool: %s · HEIC: %s", __version__, cfg.data_dir,
                 "sim" if exiftool.available else "não", "sim" if media.HEIF_OK else "não")
        yield
        if cfg.workers:
            worker.stop()
        exiftool.close()
        lock.close()

    app = FastAPI(title="Acervo", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.state.config = cfg
    app.state.exiftool = exiftool
    app.state.ingestor = ingestor
    app.state.worker = worker if cfg.workers else None
    app.state.gazetteer = gazetteer
    app.state.reconcile_report = {}

    for router in (health.router, auth_api.router, auth_api.tokens_router, items.router, albums.router,
                   uploads.router, archive.router, push_api.router, migration.router):
        app.include_router(router)

    app.state.migration_active = None  # unknown until first checked

    @app.middleware("http")
    async def migration_guard(request: Request, call_next):
        """While migrating to a new server, this one is read-only (consistent copy)."""
        path = request.url.path
        if (request.method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/")
                and not path.startswith(("/api/auth/", "/api/migration/"))):
            if app.state.migration_active is None:
                app.state.migration_active = migration.migration_state(cfg)["active"]
            if app.state.migration_active:
                return JSONResponse({"detail": "Migração em andamento: este servidor está só para consulta."},
                                    status_code=423)
        return await call_next(request)

    @app.get("/ca.crt", include_in_schema=False)
    def ca_cert() -> FileResponse:
        path = cfg.subdir(CERTS_DIR) / "ca.crt"
        if not path.exists():
            raise HTTPException(404, "HTTPS próprio não configurado (acervo certificado)")
        return FileResponse(path, media_type="application/x-x509-ca-cert", filename="acervo-ca.crt")

    placeholder = resources.files("acervo.static").joinpath("index.html").read_text("utf-8")
    web_dir = cfg.web_dir

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str) -> Response:
        raise HTTPException(404, "Rota da API não existe")

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str, request: Request) -> Response:
        """The Svelte build (web/dist), with index.html for client-side routes."""
        index = web_dir / "index.html"
        if not index.exists():
            return HTMLResponse(placeholder)
        if path:
            candidate = (web_dir / path).resolve()
            if candidate.is_file() and web_dir.resolve() in candidate.parents:
                headers = {}
                if path.startswith("assets/"):
                    headers["Cache-Control"] = "public, max-age=31536000, immutable"
                elif path in ("sw.js", "manifest.webmanifest"):
                    headers["Cache-Control"] = "no-cache"
                return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def app_factory() -> FastAPI:
    """Entry point for uvicorn (--factory). Reads config from $ACERVO_CONFIG."""
    return create_app(load_config())


__all__ = ["create_app", "app_factory", "prepare"]
