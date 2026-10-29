"""Regression tests for the independent review of version 0.2.
Each one reproduced a real problem before the fix."""

import base64
import threading

import pytest
from fastapi.testclient import TestClient

from acervo import db, migrate, push
from acervo.app import create_app
from acervo.config import Config
from conftest import Api, login, make_jpeg, sha
from test_v02 import migration_token


def q(cfg, sql, *a):
    c = db.connect(cfg.db_path)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def test_c1_upload_in_flight_when_migration_starts_is_not_lost(tmp_path):
    old_cfg = Config(data_dir=tmp_path / "old", workers=False, web_dir=tmp_path / "x")
    new_cfg = Config(data_dir=tmp_path / "new", workers=False, web_dir=tmp_path / "x")
    with TestClient(create_app(old_cfg)) as old:
        o = Api(old, old_cfg, login(old, old_cfg))
        o.upload(make_jpeg(tmp_path / "IMG_A.JPG", pattern=1))
        ing = old.app.state.ingestor
        real = ing.ingest
        gate, entered = threading.Event(), threading.Event()

        def slow(*a, **k):  # e.g. hashing a 2 GB video
            entered.set()
            gate.wait(20)
            return real(*a, **k)

        ing.ingest = slow
        late = make_jpeg(tmp_path / "IMG_LATE.JPG", pattern=7)
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", o.post(
            "/api/upload", params={"source": "iphone-manual"}, content=late.read_bytes(),
            headers={"X-Filename": "IMG_LATE.JPG"})))
        t.start()
        assert entered.wait(10)
        threading.Timer(1.5, gate.set).start()  # the upload finishes while the freeze is waiting
        report = migrate.run(new_cfg, migrate.Source("http://old", migration_token(old_cfg), client=old),
                             progress=lambda m: None)
        t.join()
        ing.ingest = real
        assert out["r"].json()["status"] == "new"
    assert report.failed == []
    assert sha(late) in {r[0] for r in q(new_cfg, "SELECT sha256 FROM items")}


def test_c1_old_server_changing_after_snapshot_is_reported(tmp_path, monkeypatch):
    old_cfg = Config(data_dir=tmp_path / "old", workers=False, web_dir=tmp_path / "x")
    new_cfg = Config(data_dir=tmp_path / "new", workers=False, web_dir=tmp_path / "x")
    with TestClient(create_app(old_cfg)) as old:
        o = Api(old, old_cfg, login(old, old_cfg))
        o.upload(make_jpeg(tmp_path / "IMG_A.JPG", pattern=1))
        src = migrate.Source("http://old", migration_token(old_cfg), client=old)
        real_download = migrate._download

        def sneaky(source, entry, dest, report):  # something writes behind the freeze's back
            c = db.connect(old_cfg.db_path)
            c.execute("INSERT INTO events (actor, action) VALUES ('teste', 'mudança tardia')")
            c.close()
            return real_download(source, entry, dest, report)

        monkeypatch.setattr(migrate, "_download", sneaky)
        report = migrate.run(new_cfg, src, progress=lambda m: None)
    assert any("mudou durante a cópia" in f for f in report.failed)
    assert (new_cfg.data_dir / migrate.STATE_FILE).exists()  # not declared complete


def test_c1_restart_while_frozen_changes_nothing(tmp_path):
    cfg = Config(data_dir=tmp_path / "old", workers=False, web_dir=tmp_path / "x")
    with TestClient(create_app(cfg)) as c:
        login(c, cfg)
        migrate.Source("http://x", migration_token(cfg), client=c).json("POST", "/api/migration/start")
    stray = make_jpeg(cfg.data_dir / "entrada" / "2024" / "IMG_STRAY.JPG", pattern=11)
    before = q(cfg, "SELECT max(id) FROM events")[0][0]
    with TestClient(create_app(cfg)):
        pass
    assert q(cfg, "SELECT count(*) FROM items WHERE sha256 = ?", sha(stray))[0][0] == 0
    assert q(cfg, "SELECT max(id) FROM events")[0][0] == before


def test_c2_original_named_part_survives_restart(cfg, tmp_path):
    p = tmp_path / "backup.part"
    p.write_bytes(b"precious document bytes " * 100)
    with TestClient(create_app(cfg)) as c:
        a = Api(c, cfg, login(c, cfg))
        r = a.upload(p)
        rel = q(cfg, "SELECT rel_path FROM files WHERE item_id = ?", r["item_id"])[0][0]
    with TestClient(create_app(cfg)):
        pass
    assert (cfg.data_dir / rel).read_bytes() == p.read_bytes()


def test_h3_shortcut_token_cannot_touch_migration(cfg):
    from acervo.certs import generate
    with TestClient(create_app(cfg)) as c:
        a = Api(c, cfg, login(c, cfg))
        generate(cfg.subdir("certificados"), ["192.168.0.50"])
        shortcut = a.post("/api/tokens", json={"label": "iPhone"}).json()["token"]
        h = {"Authorization": f"Bearer {shortcut}"}
        assert c.post("/api/migration/start", headers=h).status_code == 401
        assert c.get("/api/migration/file", params={"kind": "aux", "path": "certificados/ca.key"},
                     headers=h).status_code == 401
        mig = {"Authorization": f"Bearer {migration_token(cfg)}"}
        assert c.get("/api/stats", headers=mig).status_code == 401  # and the migration token opens nothing else
        assert a.get("/api/stats").status_code == 200


def test_h3_migration_token_expires_and_is_revoked_on_the_new_server(tmp_path):
    from acervo import auth
    old_cfg = Config(data_dir=tmp_path / "old", workers=False, web_dir=tmp_path / "x")
    new_cfg = Config(data_dir=tmp_path / "new", workers=False, web_dir=tmp_path / "x")
    with TestClient(create_app(old_cfg)) as old:
        login(old, old_cfg)
        token = migration_token(old_cfg)
        assert q(old_cfg, "SELECT expires_at IS NOT NULL FROM auth_tokens WHERE kind = 'migration'")[0][0] == 1
        migrate.run(new_cfg, migrate.Source("http://old", token, client=old), progress=lambda m: None)
    c = db.connect(new_cfg.db_path)
    try:
        assert auth.token_valid(c, token) is None
    finally:
        c.close()


def test_h4_resume_only_needs_space_for_what_is_missing(tmp_path, monkeypatch):
    import shutil
    old_cfg = Config(data_dir=tmp_path / "old", workers=False, web_dir=tmp_path / "x")
    new_cfg = Config(data_dir=tmp_path / "new", workers=False, web_dir=tmp_path / "x")
    with TestClient(create_app(old_cfg)) as old:
        o = Api(old, old_cfg, login(old, old_cfg))
        for i in range(3):
            o.upload(make_jpeg(tmp_path / f"IMG_{i}.JPG", pattern=i + 1, size=(800, 600)))
        src = migrate.Source("http://old", migration_token(old_cfg), client=old)
        real_dl = migrate._download
        calls = {"n": 0}

        def flaky(source, entry, dest, report):
            calls["n"] += 1
            if calls["n"] == 1:
                report.failed.append(entry["path"] + ": rede caiu")
                return
            return real_dl(source, entry, dest, report)

        monkeypatch.setattr(migrate, "_download", flaky)
        assert migrate.run(new_cfg, src, progress=lambda m: None).failed
        monkeypatch.setattr(migrate, "_download", real_dl)
        total = src.json("GET", "/api/migration/manifest")["total_bytes"]
        usage = type(shutil.disk_usage("/"))
        monkeypatch.setattr(migrate.shutil, "disk_usage", lambda p: usage(10**12, 10**12 - total // 2, total // 2))
        assert migrate.run(new_cfg, src, progress=lambda m: None).failed == []


def _keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64(pub), b64(b"0123456789abcdef")


def test_h5_bad_push_keys_are_refused_and_never_block_others(api, monkeypatch):
    res = api.post("/api/push/subscribe", json={"subscription": {"endpoint": "https://a.example/bad",
                   "keys": {"p256dh": "AAAA", "auth": "AAAA"}}})
    assert res.status_code == 400
    # one already stored with broken keys (e.g. from an older version) must not stop the rest
    c = db.connect(api.cfg.db_path)
    c.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, topics) VALUES "
              "('https://a.example/bad', 'AAAA', 'AAAA', '[\"backup_concluido\"]')")
    c.close()
    p256dh, auth = _keys()
    api.post("/api/push/subscribe", json={"subscription": {"endpoint": "https://a.example/good",
                                                           "keys": {"p256dh": p256dh, "auth": auth}}})
    import urllib.request

    class Ok:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Ok())
    assert push.deliver(api.cfg, "backup_concluido", "t", "b") == 1
    assert [r[0] for r in q(api.cfg, "SELECT endpoint FROM push_subscriptions")] == ["https://a.example/good"]


def test_low_push_payload_is_kept_within_one_record():
    import http_ece
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    with pytest.raises(ValueError):
        push.encrypt(b"x" * 4090, b64(pub), b64(b"0123456789abcdef"))
    data = push._fit({"title": "t", "body": "x" * 5000})
    body = push.encrypt(data, b64(pub), b64(b"0123456789abcdef"))
    assert http_ece.decrypt(body, private_key=key, auth_secret=b"0123456789abcdef", version="aes128gcm") == data


def test_m6_keep_clean_waits_for_near_duplicate_check(api, tmp_path):
    p1 = make_jpeg(tmp_path / "IMG_1.JPG", pattern=3)
    p2 = make_jpeg(tmp_path / "IMG_2.JPG", pattern=3, date="2024:05:01 10:12:34")  # near-identical
    i1, i2 = api.upload(p1)["item_id"], api.upload(p2)["item_id"]
    assert api.post("/api/inbox/keep-clean").json()["kept"] == 0
    api.run_jobs()
    assert api.get("/api/inbox/summary").json()["flagged"] == 2
    assert {api.item(i1)["state"], api.item(i2)["state"]} == {"inbox"}


def test_m11_daily_summary_is_per_run(api, tmp_path):
    for i in range(2):
        api.upload(make_jpeg(tmp_path / f"IMG_{i}.JPG", color=(i * 90, 9, 9)), source="iphone-daily")
    assert api.post("/api/daily/finish").json()["summary_text"] == "Backup diário: 2 fotos, 0 vídeos"
    assert api.post("/api/daily/finish").json()["summary_text"] == "Backup diário: nada novo"
    api.upload(make_jpeg(tmp_path / "IMG_9.JPG", color=(1, 99, 9)), source="iphone-daily")
    assert api.post("/api/daily/finish").json()["summary_text"] == "Backup diário: 1 foto, 0 vídeos"


def test_low_safe_mode_ipv4_mapped(cfg):
    with TestClient(create_app(cfg), client=("::ffff:100.101.102.103", 5000)) as client:
        a = Api(client, cfg, login(client, cfg))
        assert a.get("/api/auth/status").json()["remote"] is True
        assert a.post("/api/trash/purge-expired").status_code == 403
