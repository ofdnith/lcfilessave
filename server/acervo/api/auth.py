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
    return {"password_set": has_password, "authenticated": auth.identify(request) is not None,
            "method": auth.identify(request)}


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


@router.post("/app-token", dependencies=[Depends(auth.require_auth)])
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
