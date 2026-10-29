"""/api/push/* — the iPhone PWA asks for notifications."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import auth, db, push

router = APIRouter(prefix="/api/push", dependencies=[Depends(auth.require_auth)])


@router.get("/key")
def key(request: Request) -> dict:
    if not push.available():
        raise HTTPException(404, "Avisos indisponíveis neste servidor (falta o pacote cryptography).")
    return {"public_key": push.public_key(request.app.state.config)}


class Keys(BaseModel):
    p256dh: str
    auth: str


class Subscription(BaseModel):
    endpoint: str = Field(pattern=r"^https://")
    keys: Keys


class SubscribeBody(BaseModel):
    subscription: Subscription
    topics: list[str] = list(push.TOPICS)


@router.post("/subscribe")
def subscribe(body: SubscribeBody, request: Request) -> dict:
    topics = [t for t in body.topics if t in push.TOPICS]
    conn = db.connect(request.app.state.config.db_path)
    try:
        conn.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, topics) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth, "
            "topics = excluded.topics, failures = 0",
            (body.subscription.endpoint, body.subscription.keys.p256dh, body.subscription.keys.auth, json.dumps(topics)))
    finally:
        conn.close()
    return {"ok": True, "topics": topics}


class EndpointBody(BaseModel):
    endpoint: str


@router.post("/unsubscribe")
def unsubscribe(body: EndpointBody, request: Request) -> dict:
    conn = db.connect(request.app.state.config.db_path)
    try:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (body.endpoint,))
    finally:
        conn.close()
    return {"ok": True}


@router.get("/status")
def status(endpoint: str, request: Request) -> dict:
    conn = db.connect(request.app.state.config.db_path)
    try:
        row = conn.execute("SELECT topics FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).fetchone()
    finally:
        conn.close()
    return {"subscribed": row is not None, "topics": json.loads(row[0]) if row else []}


@router.post("/test")
def test(body: EndpointBody, request: Request) -> dict:
    cfg = request.app.state.config
    conn = db.connect(cfg.db_path)
    try:
        row = conn.execute("SELECT * FROM push_subscriptions WHERE endpoint = ?", (body.endpoint,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "Este aparelho não está inscrito nos avisos.")
    status_code = push.send_one(cfg, dict(row), {"title": "Acervo", "body": "Avisos do Acervo funcionando",
                                                 "url": "/#/ajustes", "topic": "teste"})
    if not 200 <= status_code < 300:
        raise HTTPException(502, f"O serviço de avisos recusou ({status_code}). Tente reativar os avisos.")
    return {"ok": True}
