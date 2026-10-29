"""/api/auth/* — login, logout, status, token for the Mac app."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth, db
from ..catalog import transaction

router = APIRouter(prefix="/api/auth")


class LoginBody(BaseModel):
    password: str
    client: str | None = None


@router.get("/status")
def status(request: Request) -> dict:
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        has_password = auth.password_set(conn)
    finally:
        conn.close()
    method = auth.identify(request)
    return {"password_set": has_password, "authenticated": method is not None, "method": method,
            "remote": auth.is_remote(request), "readonly": auth.readonly(request)}


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    cfg = request.app.state.config
    addr = auth.client_addr(request)
    if auth.login_blocked(addr):
        raise HTTPException(429, "Muitas tentativas erradas. Espere 10 minutos.")
    conn = db.connect(cfg.db_path)
    try:
        stored = conn.execute("SELECT value FROM settings WHERE key = 'password_hash'").fetchone()
        if stored is None:
            raise HTTPException(409, "Nenhuma senha definida. No servidor, rode: acervo senha")
        if not auth.check_password(body.password, stored[0]):
            auth.record_failure(addr)
            raise HTTPException(401, "Senha errada.")
        auth.clear_failures(addr)
        with transaction(conn):
            token = auth.create_token(conn, "session", body.client or request.headers.get("user-agent", "navegador")[:80])
    finally:
        conn.close()
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https", path="/")
    return {"token": token}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        for token in filter(None, (request.cookies.get(auth.COOKIE), auth.bearer(request))):
            auth.revoke_token(conn, token)
    finally:
        conn.close()
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.post("/app-token", dependencies=[Depends(auth.require_auth), Depends(auth.forbid_remote)])
def app_token(request: Request) -> dict:
    """Long-lived token for the Mac app's native commands (downloads to drives, uploads)."""
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        if not auth.password_set(conn):
            raise HTTPException(409, "Defina uma senha no servidor antes (acervo senha).")
        with transaction(conn):
            token = auth.create_token(conn, "api", "App do Mac")
    finally:
        conn.close()
    return {"token": token}


# --- tokens for the iPhone Shortcuts, managed from the interface ----------------------------

tokens_router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_auth)])


@tokens_router.get("/tokens")
def list_tokens(request: Request) -> dict:
    conn = db.connect(request.app.state.config.db_path)
    try:
        rows = conn.execute("SELECT id, label, created_at, last_used_at FROM auth_tokens "
                            "WHERE kind = 'api' AND revoked_at IS NULL ORDER BY id DESC").fetchall()
    finally:
        conn.close()
    return {"tokens": [dict(r) for r in rows]}


class TokenBody(BaseModel):
    label: str = "iPhone"


@tokens_router.post("/tokens", dependencies=[Depends(auth.forbid_remote)])
def create_api_token(body: TokenBody, request: Request) -> dict:
    conn = db.connect(request.app.state.config.db_path)
    try:
        if not auth.password_set(conn):
            raise HTTPException(409, "Defina uma senha no servidor antes (acervo senha).")
        with transaction(conn):
            token = auth.create_token(conn, "api", body.label.strip() or "iPhone")
            tid = conn.execute("SELECT max(id) FROM auth_tokens").fetchone()[0]
    finally:
        conn.close()
    return {"id": tid, "token": token}


@tokens_router.delete("/tokens/{token_id}", dependencies=[Depends(auth.forbid_remote)])
def revoke_api_token(token_id: int, request: Request) -> dict:
    conn = db.connect(request.app.state.config.db_path)
    try:
        conn.execute("UPDATE auth_tokens SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                     "WHERE id = ? AND kind = 'api'", (token_id,))
    finally:
        conn.close()
    return {"ok": True}


@tokens_router.get("/shortcuts")
def shortcuts(request: Request) -> dict:
    cfg = request.app.state.config
    return {"links": {"manual": cfg.shortcut_manual_url or None, "daily": cfg.shortcut_daily_url or None}}
