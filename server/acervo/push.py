"""Web Push notifications to the iPhone PWA (iOS 16.4+), no third-party service.

The server only makes OUTGOING requests to the browser's push service (Apple
for Safari); nothing is opened to the internet (rule 7). Implemented directly
on `cryptography` (Termux: pkg install python-cryptography):
  * message encryption: RFC 8291 (aes128gcm)
  * server identity: VAPID (RFC 8292), ES256 JWT; key in certificados/vapid.pem

Topics a device can subscribe to:
  backup_atrasado   daily backup older than 48 h
  espaco            server above the storage alert
  hd_problema       a drive health check found a problem
  backup_concluido  summary at the end of each daily backup
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import db
from .catalog import now_iso
from .config import CERTS_DIR, Config

log = logging.getLogger(__name__)

TOPICS = ("backup_atrasado", "espaco", "hd_problema", "backup_concluido")
MAX_FAILURES = 10


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _crypto():
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    except ImportError:
        return None
    return hashes, serialization, ec, decode_dss_signature, AESGCM, HKDF


def available() -> bool:
    return _crypto() is not None


# --- VAPID key --------------------------------------------------------------------------------

_key_lock = threading.Lock()


def _vapid_key(cfg: Config):
    hashes, serialization, ec, *_ = _crypto()
    path = cfg.subdir(CERTS_DIR) / "vapid.pem"
    with _key_lock:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            key = ec.generate_private_key(ec.SECP256R1())
            path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
            os.chmod(path, 0o600)
        return serialization.load_pem_private_key(path.read_bytes(), password=None)


def public_key(cfg: Config) -> str:
    _, serialization, *_ = _crypto()
    raw = _vapid_key(cfg).public_key().public_bytes(serialization.Encoding.X962,
                                                    serialization.PublicFormat.UncompressedPoint)
    return _b64u(raw)


def _vapid_header(cfg: Config, endpoint: str) -> str:
    hashes, serialization, ec, decode_dss_signature, *_ = _crypto()
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": cfg.push_contact}
    signing_input = (_b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode()) + "." +
                     _b64u(json.dumps(claims, separators=(",", ":")).encode()))
    der = _vapid_key(cfg).sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    jwt = signing_input + "." + _b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jwt}, k={public_key(cfg)}"


# --- RFC 8291 encryption -------------------------------------------------------------------------

def encrypt(payload: bytes, p256dh: str, auth_secret: str) -> bytes:
    hashes, serialization, ec, _, AESGCM, HKDF = _crypto()
    ua_public = _unb64u(p256dh)
    auth = _unb64u(auth_secret)
    as_private = ec.generate_private_key(ec.SECP256R1())
    as_public = as_private.public_key().public_bytes(serialization.Encoding.X962,
                                                     serialization.PublicFormat.UncompressedPoint)
    ecdh = as_private.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = HKDF(hashes.SHA256(), 32, salt=auth, info=b"WebPush: info\x00" + ua_public + as_public).derive(ecdh)
    salt = os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_public)) + as_public + ciphertext


# --- sending ------------------------------------------------------------------------------------

def send_one(cfg: Config, sub: dict, message: dict) -> int:
    """POST one notification. Returns the HTTP status (201 = accepted)."""
    body = encrypt(json.dumps(message, ensure_ascii=False).encode(), sub["p256dh"], sub["auth"])
    req = urllib.request.Request(sub["endpoint"], data=body, method="POST", headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "TTL": "86400", "Urgency": "normal", "Authorization": _vapid_header(cfg, sub["endpoint"])})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return 0  # offline: counts as a failure, retried next time


def deliver(cfg: Config, topic: str, title: str, body: str, url: str = "/") -> int:
    """Send to every device subscribed to `topic`. Returns how many accepted."""
    if not available():
        return 0
    conn = db.connect(cfg.db_path)
    try:
        subs = [dict(r) for r in conn.execute("SELECT * FROM push_subscriptions")]
    finally:
        conn.close()
    sent = 0
    for sub in subs:
        if topic != "teste" and topic not in json.loads(sub["topics"]):
            continue
        status = send_one(cfg, sub, {"title": title, "body": body, "url": url, "topic": topic})
        conn = db.connect(cfg.db_path)
        try:
            if 200 <= status < 300:
                sent += 1
                conn.execute("UPDATE push_subscriptions SET last_ok_at = ?, failures = 0 WHERE id = ?",
                             (now_iso(), sub["id"]))
            elif status in (404, 410):  # the device unsubscribed / reinstalled the app
                conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
            else:
                conn.execute("UPDATE push_subscriptions SET failures = failures + 1 WHERE id = ?", (sub["id"],))
                conn.execute("DELETE FROM push_subscriptions WHERE id = ? AND failures >= ?", (sub["id"], MAX_FAILURES))
                log.info("Aviso não entregue (%s) para %s", status, urlsplit(sub["endpoint"]).netloc)
        finally:
            conn.close()
    return sent


def notify(cfg: Config, topic: str, title: str, body: str, url: str = "/") -> None:
    """Fire-and-forget: never slows down or breaks the request that triggered it."""
    def run():
        try:
            deliver(cfg, topic, title, body, url)
        except Exception:
            log.exception("Falha ao enviar aviso")
    threading.Thread(target=run, name="acervo-push", daemon=True).start()


__all__ = ["TOPICS", "available", "public_key", "encrypt", "send_one", "deliver", "notify"]
