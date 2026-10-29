"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from importlib import resources

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from . import __version__, db
from .api import health
from .config import Config, load_config
from .storage import ensure_layout

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
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        prepare(cfg)
        log.info("Acervo %s pronto · dados em %s", __version__, cfg.data_dir)
        yield

    app = FastAPI(
        title="Acervo",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.config = cfg
    app.include_router(health.router)

    # Phase 0 placeholder page; phase 1 replaces it with the Svelte build.
    index_html = resources.files("acervo.static").joinpath("index.html").read_text("utf-8")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return index_html

    return app


def app_factory() -> FastAPI:
    """Entry point for uvicorn (--factory). Reads config from $ACERVO_CONFIG."""
    return create_app(load_config())
