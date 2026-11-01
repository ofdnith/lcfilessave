"""Version 0.2: medium previews, one-tap triage, memories, places, albums,
tokens for the Shortcuts, simplified daily backup, Web Push, safe mode away
from home, and migration to a new server."""

import base64
import hashlib
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from acervo import db, push
from acervo.app import create_app
from conftest import Api, login, make_jpeg, sha


def q(cfg, sql, *a):
    c = db.connect(cfg.db_path)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


# --- 1. medium previews -----------------------------------------------------------------------

def test_medium_preview_survives_archiving(api, tmp_path):
    from test_archive import archive_everything
    iid = api.upload(make_jpeg(tmp_path / "IMG_M.JPG", size=(3000, 2000), pattern=5))["item_id"]
    api.run_jobs()
    item = api.item(iid)
    assert item["medium_url"]
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(api.get(item["medium_url"]).content))
    assert max(im.size) == 1024 and im.format == "WEBP"
    api.act([iid], "keep")
    archive_everything(api, tmp_path / "hd")
    item = api.item(iid)
    assert item["state"] == "archived" and item["original_url"] is None
    assert api.get(item["medium_url"]).status_code == 200  # still good quality away from the drive


def test_medium_backfill_for_old_items(api, tmp_path):
    iid = api.upload(make_jpeg(tmp_path / "IMG_B.JPG"))["item_id"]
    api.run_jobs()
    c = db.connect(api.cfg.db_path)
    c.execute("UPDATE items SET medium_status = 'pending' WHERE id = ?", (iid,))  # as after the upgrade
    c.close()
    from acervo.jobs import Worker
    from acervo.places import Gazetteer
    Worker(api.cfg, None, Gazetteer(api.cfg.subdir("geo"))).maintenance()
    api.run_jobs()
    assert api.item(iid)["medium_url"]


# --- 4. one-tap triage ---------------------------------------------------------------------------

def test_keep_everything_except_suggestions(api, tmp_path):
    clean = [api.upload(make_jpeg(tmp_path / f"IMG_{i}.JPG", color=(i * 50, 10, 10), pattern=i + 1))["item_id"]
             for i in range(3)]
    wa = api.upload(make_jpeg(tmp_path / "IMG-20240101-WA0001.jpg", color=(1, 200, 1), pattern=9))["item_id"]
    # Right after the backup nothing has been analysed yet: nothing is kept in one tap.
    assert api.get("/api/inbox/summary").json() == {"total": 4, "flagged": 1, "processing": 3, "clean": 0}
    assert api.post("/api/inbox/keep-clean").json() == {"kept": 0, "flagged_left": 4}
    api.run_jobs()
    assert api.get("/api/inbox/summary").json() == {"total": 4, "flagged": 1, "processing": 0, "clean": 3}
    res = api.post("/api/inbox/keep-clean").json()
    assert res == {"kept": 3, "flagged_left": 1}
    assert {api.item(i)["state"] for i in clean} == {"library"}
    assert api.item(wa)["state"] == "inbox"


# --- 5. memories, places, map, albums ---------------------------------------------------------

def test_memories_on_this_day(api, tmp_path):
    ids = {}
    for year in (2019, 2022, 2022):
        p = make_jpeg(tmp_path / f"y{year}-{len(ids)}" / "IMG.JPG", color=(year % 255, len(ids) * 40, 9),
                      date=f"{year}:10:29 09:00:00")
        ids.setdefault(year, []).append(api.upload(p)["item_id"])
    other = api.upload(make_jpeg(tmp_path / "IMG_X.JPG", date="2022:10:30 09:00:00"))["item_id"]
    api.act([*ids[2019], *ids[2022], other], "keep")
    mem = api.get("/api/memories", params={"date": "10-29"}).json()
    assert [y["year"] for y in mem["years"]] == [2022, 2019]
    assert mem["years"][0]["count"] == 2 and mem["years"][0]["years_ago"] > 0
    assert api.get("/api/memories", params={"date": "01-01"}).json()["years"] == []


def test_places_and_map(api, tmp_path):
    geo = api.cfg.subdir("geo")
    (geo / "cities.txt").write_text(
        "3448439\tSão Paulo\tSao Paulo\t\t-23.5475\t-46.63611\tP\tPPLA\tBR\t\t27\t\t\t\t1\t\t\tx\t2023\n")
    (geo / "admin1.txt").write_text("BR.27\tSão Paulo\tSao Paulo\t1\n")
    (geo / "countries.txt").write_text("BR\tBRA\t076\tBR\tBrasil\n")
    ids = [api.upload(make_jpeg(tmp_path / f"IMG_{i}.JPG", color=(i * 70, 5, 5), gps=(-23.55, -46.64)))["item_id"]
           for i in range(2)]
    api.run_jobs()
    api.act(ids, "keep")
    places = api.get("/api/places").json()["places"]
    assert places[0]["place"] == "São Paulo, São Paulo, Brasil" and places[0]["count"] == 2
    assert places[0]["cover"]["id"] in ids
    points = api.get("/api/map/points").json()["points"]
    assert sorted(p[0] for p in points) == sorted(ids)
    listed = api.get("/api/items", params={"place": "São Paulo, São Paulo, Brasil"}).json()
    assert listed["total"] == 2


def test_albums(api, tmp_path):
    ids = [api.upload(make_jpeg(tmp_path / f"IMG_{i}.JPG", color=(i * 70, 5, 5)))["item_id"] for i in range(3)]
    api.act(ids[:2], "keep")  # the third stays in the Entrada: albums show it anyway
    alb = api.post("/api/albums", json={"name": "Viagem Chile 2024"}).json()
    assert api.post(f"/api/albums/{alb['id']}/items", json={"ids": ids}).json() == {"added": 3}
    assert api.post(f"/api/albums/{alb['id']}/items", json={"ids": ids}).json() == {"added": 0}
    listed = api.get("/api/items", params={"album_id": alb["id"]}).json()
    assert listed["total"] == 3
    assert api.item(ids[0])["albums"] == [{"id": alb["id"], "name": "Viagem Chile 2024"}]
    res = api.client.patch(f"/api/albums/{alb['id']}", json={"name": "Chile", "cover_item_id": ids[1]},
                           headers=api.headers).json()
    assert res["name"] == "Chile" and res["cover"]["id"] == ids[1]
    api.post(f"/api/albums/{alb['id']}/items/remove", json={"ids": [ids[1]]})
    assert api.get("/api/albums").json()["albums"][0]["count"] == 2
    api.client.delete(f"/api/albums/{alb['id']}", headers=api.headers)
    assert api.get("/api/albums").json()["albums"] == []
    assert all(api.item(i)["state"] in ("library", "inbox") for i in ids)  # items untouched


# --- 2. Shortcuts: tokens from the interface and a session-less daily backup -----------------------

def test_tokens_from_the_interface(api):
    created = api.post("/api/tokens", json={"label": "iPhone"}).json()
    assert created["token"] and created["id"]
    listed = api.get("/api/tokens").json()["tokens"]
    assert any(t["id"] == created["id"] and t["label"] == "iPhone" for t in listed)
    h = {"Authorization": f"Bearer {created['token']}"}
    assert api.client.get("/api/stats", headers=h).status_code == 200
    api.client.delete(f"/api/tokens/{created['id']}", headers=api.headers)
    assert api.client.get("/api/stats", headers=h).status_code == 401


def test_daily_backup_without_sessions(api, tmp_path):
    for i in range(2):
        api.upload(make_jpeg(tmp_path / f"IMG_{i}.JPG", color=(i * 90, 9, 9)), source="iphone-daily")
    sessions = q(api.cfg, "SELECT count(*) FROM upload_sessions WHERE source = 'iphone-daily'")[0][0]
    assert sessions == 1  # both joined today's session
    done = api.post("/api/daily/finish").json()
    assert done["summary_text"] == "Backup diário: 2 fotos, 0 vídeos"
    assert api.get("/api/daily").json()["last_at"]
    again = api.post("/api/daily/finish").json()
    assert again["summary_text"].startswith("Backup diário")


def test_shortcut_links(cfg):
    cfg2 = replace(cfg, shortcut_daily_url="https://www.icloud.com/shortcuts/abc")
    with TestClient(create_app(cfg2)) as client:
        a = Api(client, cfg2, login(client, cfg2))
        assert a.get("/api/shortcuts").json()["links"] == {"manual": None, "daily": "https://www.icloud.com/shortcuts/abc"}


# --- 3. Web Push ---------------------------------------------------------------------------------

def _browser_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = b"0123456789abcdef"
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    return key, b64(pub), b64(auth), auth


def test_push_payload_decrypts_like_a_browser():
    import http_ece
    key, p256dh, auth_b64, auth = _browser_keys()
    body = push.encrypt(b'{"title":"Acervo"}', p256dh, auth_b64)
    assert http_ece.decrypt(body, private_key=key, auth_secret=auth, version="aes128gcm") == b'{"title":"Acervo"}'


def test_push_subscribe_topics_and_delivery(api, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "send_one", lambda cfg, sub, msg: sent.append((sub["endpoint"], msg)) or 201)
    assert api.get("/api/push/key").json()["public_key"]
    _, p256dh, auth_b64, _ = _browser_keys()
    sub = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": p256dh, "auth": auth_b64}}
    api.post("/api/push/subscribe", json={"subscription": sub, "topics": ["backup_concluido", "x"]})
    assert api.get("/api/push/status", params={"endpoint": sub["endpoint"]}).json() == {
        "subscribed": True, "topics": ["backup_concluido"]}
    assert push.deliver(api.cfg, "backup_concluido", "Backup diário", "2 fotos") == 1
    assert push.deliver(api.cfg, "espaco", "x", "y") == 0  # not subscribed to this topic
    assert sent[0][1]["body"] == "2 fotos"
    assert api.post("/api/push/test", json={"endpoint": sub["endpoint"]}).json() == {"ok": True}


def test_push_gone_subscription_is_removed(api, monkeypatch):
    monkeypatch.setattr(push, "send_one", lambda cfg, sub, msg: 410)
    _, p256dh, auth_b64, _ = _browser_keys()
    api.post("/api/push/subscribe", json={"subscription": {"endpoint": "https://x.example/1",
                                                           "keys": {"p256dh": p256dh, "auth": auth_b64}}})
    push.deliver(api.cfg, "backup_concluido", "a", "b")
    assert q(api.cfg, "SELECT count(*) FROM push_subscriptions")[0][0] == 0


def test_vapid_header_is_a_valid_es256_jwt(api):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    header = push._vapid_header(api.cfg, "https://web.push.apple.com/abc")
    t = header.split("t=")[1].split(",")[0]
    k = header.split("k=")[1]
    head, claims, sig = t.split(".")
    un = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))  # noqa: E731
    assert json.loads(un(claims))["aud"] == "https://web.push.apple.com"
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), un(k))
    raw = un(sig)
    pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
               f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


# --- 6. safe mode away from home -------------------------------------------------------------------

def test_safe_mode_through_tailscale(cfg, tmp_path):
    with TestClient(create_app(cfg), client=("100.101.102.103", 5000)) as client:
        token = login(client, cfg)
        a = Api(client, cfg, token)
        st = a.get("/api/auth/status").json()
        assert st["remote"] is True and st["readonly"] is True
        iid = a.upload(make_jpeg(tmp_path / "IMG_S.JPG"))["item_id"]  # sending is fine
        assert a.post("/api/items/actions", json={"ids": [iid], "action": "keep"}).status_code == 200
        res = a.post("/api/items/actions", json={"ids": [iid], "action": "discard"})
        assert res.status_code == 403 and "modo seguro" in res.json()["detail"]
        assert a.post("/api/trash/purge-expired").status_code == 403
        assert a.post("/api/volumes", json={"capacity_bytes": 10**12}).status_code == 403
        assert a.post("/api/tokens", json={"label": "x"}).status_code == 403
        assert a.post("/api/migration/start").status_code == 403
        assert a.get(f"/api/items/{iid}").status_code == 200  # viewing is fine
    with TestClient(create_app(cfg), client=("192.168.0.20", 5000)) as client:  # at home
        a = Api(client, cfg, token)
        assert a.get("/api/auth/status").json()["readonly"] is False
        assert a.post("/api/items/actions", json={"ids": [iid], "action": "discard"}).status_code == 200


def test_full_mode_allows_everything_remotely(cfg, tmp_path):
    cfg2 = replace(cfg, remote_mode="completo")
    with TestClient(create_app(cfg2), client=("100.101.102.103", 5000)) as client:
        a = Api(client, cfg2, login(client, cfg2))
        assert a.get("/api/auth/status").json()["readonly"] is False


# --- migration -------------------------------------------------------------------------------------

def migration_token(cfg) -> str:
    from acervo import auth
    from acervo.catalog import transaction
    c = db.connect(cfg.db_path)
    try:
        with transaction(c):
            return auth.create_token(c, "migration", "migracao")
    finally:
        c.close()


def test_migration_to_a_new_server(tmp_path):
    from acervo import migrate
    from acervo.config import Config
    from acervo.library import apply_action
    old_cfg = Config(data_dir=tmp_path / "realme", workers=False, web_dir=tmp_path / "x")
    new_cfg = Config(data_dir=tmp_path / "minipc", workers=False, web_dir=tmp_path / "x")
    photos = [make_jpeg(tmp_path / "src" / f"IMG_{i}.JPG", color=(i * 60, 9, 9), pattern=i + 1) for i in range(4)]
    with TestClient(create_app(old_cfg)) as old:
        o = Api(old, old_cfg, login(old, old_cfg))
        ids = [o.upload(p)["item_id"] for p in photos]
        o.run_jobs()
        o.act(ids[:2], "keep")
        alb = o.post("/api/albums", json={"name": "Férias"}).json()
        o.post(f"/api/albums/{alb['id']}/items", json={"ids": ids[:2]})
        shortcut_token = o.post("/api/tokens", json={"label": "iPhone"}).json()["token"]
        from acervo.certs import generate
        generate(old_cfg.subdir("certificados"), ["192.168.0.50"])

        source = migrate.Source("http://old", migration_token(old_cfg), client=old)
        report = migrate.run(new_cfg, source, progress=lambda m: None)
        assert report.failed == [] and report.originals == 4 and report.aux >= 8

        # the old server is frozen read-only, nothing deleted
        assert o.upload.__self__.post("/api/items/actions", json={"ids": [ids[2]], "action": "keep"}).status_code == 423
        assert o.get("/api/health").json()["migration"]["active"] is True
        assert all(p.read_bytes() for p in old_cfg.data_dir.rglob("*.JPG"))

        # running it again only re-checks (resumable)
        again = migrate.run(new_cfg, source, progress=lambda m: None) if (new_cfg.data_dir / ".migracao.json").exists() else None
        assert again is None  # finished cleanly: state file removed

    with TestClient(create_app(new_cfg)) as new:
        n = Api(new, new_cfg, login(new, new_cfg))
        assert n.get("/api/health").json()["status"] == "ok"
        assert n.get("/api/stats").json()["inbox_count"] == 2
        assert n.get("/api/items", params={"album_id": alb["id"]}).json()["total"] == 2
        for i, p in zip(ids, photos):
            assert hashlib.sha256(n.get(f"/api/items/{i}/original").content).hexdigest() == sha(p)
        assert n.get(f"/api/items/{ids[0]}/medium").status_code == 200
        # the iPhone Shortcut token keeps working on the new server
        assert new.get("/api/stats", headers={"Authorization": f"Bearer {shortcut_token}"}).status_code == 200
        # the same certificate authority came along (iPhone keeps trusting it)
        assert (new_cfg.subdir("certificados") / "ca.crt").read_bytes() == \
            (old_cfg.subdir("certificados") / "ca.crt").read_bytes()
        assert (new_cfg.data_dir / "MIGRACAO.txt").read_text().count("Problemas: 0") == 1
        # and the new one is NOT frozen
        assert n.post("/api/items/actions", json={"ids": [ids[2]], "action": "keep"}).status_code == 200


def test_migration_refuses_a_non_empty_destination(tmp_path):
    from acervo import migrate
    from acervo.config import Config
    cfg = Config(data_dir=tmp_path / "d", workers=False, web_dir=tmp_path / "x")
    with TestClient(create_app(cfg)) as c:
        a = Api(c, cfg, login(c, cfg))
        a.upload(make_jpeg(tmp_path / "IMG.JPG"))
        with pytest.raises(migrate.MigrationError, match="já tem um acervo"):
            migrate.run(cfg, migrate.Source("http://x", "t", client=c), progress=lambda m: None)


def test_corrupted_file_on_the_old_server_is_reported(tmp_path):
    from acervo import migrate
    from acervo.config import Config
    old_cfg = Config(data_dir=tmp_path / "old", workers=False, web_dir=tmp_path / "x")
    new_cfg = Config(data_dir=tmp_path / "new", workers=False, web_dir=tmp_path / "x")
    with TestClient(create_app(old_cfg)) as old:
        o = Api(old, old_cfg, login(old, old_cfg))
        iid = o.upload(make_jpeg(tmp_path / "IMG_Z.JPG"))["item_id"]
        rel = q(old_cfg, "SELECT rel_path FROM files WHERE item_id = ?", iid)[0][0]
        (old_cfg.data_dir / rel).write_bytes(b"bit rot")
        report = migrate.run(new_cfg, migrate.Source("http://old", migration_token(old_cfg), client=old),
                             progress=lambda m: None)
    assert report.failed and "IMG_Z" in report.failed[0]
    assert (new_cfg.data_dir / ".migracao.json").exists()  # not declared complete
    assert "Problemas: " in (new_cfg.data_dir / "MIGRACAO.txt").read_text()


def test_cancel_unfreezes_the_old_server(cfg):
    from acervo import migrate
    with TestClient(create_app(cfg)) as c:
        a = Api(c, cfg, login(c, cfg))
        src = migrate.Source("http://x", migration_token(cfg), client=c)
        src.json("POST", "/api/migration/start")
        assert a.post("/api/albums", json={"name": "x"}).status_code == 423
        migrate.cancel(src)
        assert a.post("/api/albums", json={"name": "x"}).status_code == 200


def test_fetch_several_items_by_id(api, tmp_path):
    ids = [api.upload(make_jpeg(tmp_path / f"IMG_{i}.JPG", color=(i * 70, 3, 3)))["item_id"] for i in range(3)]
    api.act([ids[0]], "keep")
    got = api.get("/api/items", params={"ids": f"{ids[0]},{ids[2]}"}).json()
    assert sorted(i["id"] for i in got["items"]) == sorted([ids[0], ids[2]])
