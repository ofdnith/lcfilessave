"""Password, login sessions and API tokens (inviolable rule 7).

  * The password is stored as an scrypt hash in `settings`.
  * Login creates a random token; only its SHA-256 is stored (`auth_tokens`).
    Browsers get it as an HttpOnly cookie, other clients as a Bearer token.
  * With no password set, only requests from this computer (loopback) pass —
    convenient while developing on the Mac. The server refuses to listen on
    the network until a password exists (see __main__).
  * 5 wrong passwords from the same address within 10 minutes -> blocked for
    the rest of those 10 minutes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import sqlite3
import threading
import time

from fastapi import HTTPException, Request

from . import db
from .catalog import get_setting, iso_in, now_iso, set_setting
from .config import is_loopback

COOKIE = "acervo_session"
SESSION_DAYS = 180
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
MIN_PASSWORD = 8


class PasswordError(ValueError):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${hash}".format(
        **_SCRYPT, salt=base64.b64encode(salt).decode(), hash=base64.b64encode(digest).decode())


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32,
                             n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(digest))


def set_password(conn: sqlite3.Connection, password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise PasswordError(f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres.")
    first_time = not password_set(conn)
    set_setting(conn, "password_hash", hash_password(password))
    if first_time:
        # Tokens created while there was no password (local mode) are not trusted.
        conn.execute("UPDATE auth_tokens SET revoked_at = ? WHERE revoked_at IS NULL", (now_iso(),))
    # A new password logs out every browser; API tokens (Atalhos, Mac) keep working.
    conn.execute("UPDATE auth_tokens SET revoked_at = ? WHERE kind = 'session' AND revoked_at IS NULL", (now_iso(),))


def password_set(conn: sqlite3.Connection) -> bool:
    return get_setting(conn, "password_hash") is not None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(conn: sqlite3.Connection, kind: str, label: str) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO auth_tokens (token_hash, kind, label, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), kind, label[:80], iso_in(SESSION_DAYS) if kind == "session" else None),
    )
    return token


def revoke_token(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("UPDATE auth_tokens SET revoked_at = ? WHERE token_hash = ?", (now_iso(), _token_hash(token)))


def token_valid(conn: sqlite3.Connection, token: str) -> str | None:
    row = conn.execute(
        "SELECT id, kind, expires_at, last_used_at FROM auth_tokens WHERE token_hash = ? AND revoked_at IS NULL",
        (_token_hash(token),),
    ).fetchone()
    if row is None or (row["expires_at"] and row["expires_at"] < now_iso()):
        return None
    if row["last_used_at"] is None or row["last_used_at"] < iso_in(-1 / 24):
        conn.execute("UPDATE auth_tokens SET last_used_at = ? WHERE id = ?", (now_iso(), row["id"]))
    return row["kind"]


# --- brute-force protection ------------------------------------------------------------

_failures: dict[str, list[float]] = {}
_fail_lock = threading.Lock()
MAX_FAILURES = 5
WINDOW_S = 600


def login_blocked(addr: str) -> bool:
    with _fail_lock:
        recent = [t for t in _failures.get(addr, []) if time.monotonic() - t < WINDOW_S]
        _failures[addr] = recent
        return len(recent) >= MAX_FAILURES


def record_failure(addr: str) -> None:
    with _fail_lock:
        _failures.setdefault(addr, []).append(time.monotonic())


def clear_failures(addr: str) -> None:
    with _fail_lock:
        _failures.pop(addr, None)


# --- request authentication ------------------------------------------------------------

def client_addr(request: Request) -> str:
    return request.client.host if request.client else ""


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def identify(request: Request) -> str | None:
    """'token' | 'cookie' | 'local' | None"""
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        token = bearer(request)
        if token and token_valid(conn, token):
            return "token"
        cookie = request.cookies.get(COOKIE)
        if cookie and token_valid(conn, cookie):
            return "cookie"
        if (not password_set(conn) and is_loopback(client_addr(request)) and not _forwarded(request)
                and _local_host(request)):
            return "local"
        return None
    finally:
        conn.close()


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _local_host(request: Request) -> bool:
    """Blocks DNS rebinding: a web page on evil.example resolving to 127.0.0.1
    still sends 'Host: evil.example', which local mode refuses."""
    host = request.headers.get("host", "")
    name = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    return name.lower() in LOCAL_HOSTS


def _forwarded(request: Request) -> bool:
    # Behind a local proxy (e.g. `tailscale serve`) the peer is 127.0.0.1 but
    # the user is remote: never treat that as "this computer".
    return any(h in request.headers for h in ("x-forwarded-for", "x-real-ip", "forwarded"))


def is_remote(request: Request) -> bool:
    """Away from home = the request comes through Tailscale (or another configured network)."""
    cfg = request.app.state.config
    try:
        addr = ipaddress.ip_address(client_addr(request))
    except ValueError:
        return False
    return any(addr in ipaddress.ip_network(net) for net in cfg.remote_networks)


def readonly(request: Request) -> bool:
    return request.app.state.config.remote_mode == "seguro" and is_remote(request)


def forbid_remote(request: Request) -> None:
    """Dependency for destructive / administrative actions (modo seguro fora de casa)."""
    if readonly(request):
        raise HTTPException(status_code=403, detail="Fora de casa o Acervo está em modo seguro: "
                                                      "apagar e mexer em HDs só pela rede de casa.")


def require_auth(request: Request) -> str:
    method = identify(request)
    if method is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    request.state.auth = method
    return method
