"""Regression tests for the independent data-safety review (numbers = findings).
Each one reproduced a real problem before the fix."""

import asyncio
import base64
import hashlib
import os
import subprocess
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from acervo import db, ingest as ingest_mod
from acervo.app import create_app, prepare
from acervo.config import Config
from acervo.ingest import reconcile
from acervo.storage import DataDirBusy, lock_data_dir
from conftest import Api, login, make_jpeg, sha


def q(cfg, sql, *a):
    c = db.connect(cfg.db_path)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def ex(cfg, sql, *a):
    c = db.connect(cfg.db_path)
    try:
        c.execute(sql, a)
    finally:
        c.close()


def make_mov(path, cid):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=5",
                    "-metadata", f"com.apple.quicktime.content.identifier={cid}", "-movflags", "use_metadata_tags",
                    str(path)], check=True)
    return path


def test_01_reupload_repairs_a_missing_server_copy(api, tmp_path):
    p = make_jpeg(tmp_path / "IMG_1.JPG")
    iid = api.upload(p)["item_id"]
    rel = q(api.cfg, "SELECT rel_path FROM files WHERE item_id=?", iid)[0][0]
    (api.cfg.data_dir / rel).unlink()  # disk lost the original
    s = api.post("/api/sessions", json={"source": "iphone-empty", "expected_count": 1}).json()
    pre = api.post("/api/precheck", json={"session_id": s["id"], "entries": [{"key": "k", "sha256": sha(p)}]}).json()
    assert pre["results"][0]["known"] is False  # must be sent again
    assert api.get(f"/api/sessions/{s['id']}").json()["safe_to_delete"] is False
    res = api.upload(p, session_id=s["id"], sha256=sha(p), client_key="k")
    assert res["status"] == "restored"
    assert (api.cfg.data_dir / rel).read_bytes() == p.read_bytes()
    assert api.get(f"/api/sessions/{s['id']}").json()["safe_to_delete"] is True


def test_01b_reupload_repairs_a_corrupted_server_copy(api, tmp_path):
    p = make_jpeg(tmp_path / "IMG_C.JPG")
    iid = api.upload(p)["item_id"]
    rel = q(api.cfg, "SELECT rel_path FROM files WHERE item_id=?", iid)[0][0]
    (api.cfg.data_dir / rel).write_bytes(b"bit rot")
    assert api.upload(p)["status"] == "restored"
    assert (api.cfg.data_dir / rel).read_bytes() == p.read_bytes()
    assert list((api.cfg.data_dir / "tmp" / "corrompidos").iterdir())  # damaged copy kept aside, not deleted


def test_02_reconcile_never_deletes_a_file_moved_meanwhile(api, tmp_path, monkeypatch):
    p = make_jpeg(tmp_path / "IMG_R.JPG")
    iid = api.upload(p)["item_id"]
    real_walk = os.walk
    state = {"done": False}

    def walk(folder, *a, **k):
        if not state["done"]:
            state["done"] = True
            api.act([iid], "keep")
        return real_walk(folder, *a, **k)

    monkeypatch.setattr(ingest_mod.os, "walk", walk)
    rep = reconcile(api.cfg, api.client.app.state.ingestor)
    rel = q(api.cfg, "SELECT rel_path FROM files WHERE item_id=?", iid)[0][0]
    assert rep["removed_copies"] == 0
    assert (api.cfg.data_dir / rel).read_bytes() == p.read_bytes()


def test_02b_verificar_refuses_while_server_runs(cfg):
    with TestClient(create_app(cfg)):
        with pytest.raises(DataDirBusy):
            lock_data_dir(cfg)
    lock_data_dir(cfg).close()  # free again after shutdown


def test_03_failed_health_check_does_not_count_as_a_copy(tmp_path):
    cfg = Config(data_dir=tmp_path / "dados", workers=False, web_dir=tmp_path / "x", archive_copies=2)
    with TestClient(create_app(cfg)) as client:
        a = Api(client, cfg, login(client, cfg))
        p = make_jpeg(tmp_path / "IMG_8.JPG")
        iid = a.upload(p)["item_id"]
        a.act([iid], "keep")
        vols = [a.post("/api/volumes", json={"capacity_bytes": 10**12}).json()["id"] for _ in range(2)]
        fid = q(cfg, "SELECT id FROM files WHERE item_id=?", iid)[0][0]
        rel = q(cfg, "SELECT rel_path FROM files WHERE id=?", fid)[0][0].split("/", 1)[1]
        a.post("/api/archive/verified", json={"volume_id": vols[0], "copies": [
            {"file_id": fid, "rel_path": rel, "sha256": sha(p)}]})
        a.post(f"/api/volumes/{vols[0]}/checks", json={"kind": "partial", "files_checked": 1,
               "problems": [{"file_id": fid, "error": "hash differs"}], "checked_file_ids": [fid]})
        a.post("/api/archive/verified", json={"volume_id": vols[1], "copies": [
            {"file_id": fid, "rel_path": rel, "sha256": sha(p)}]})
        assert a.post("/api/archive/commit", json={"volume_id": vols[1]}).json()["archived_items"] == 0
        assert a.item(iid)["on_server"]
        c = db.connect(cfg.db_path)  # the database itself refuses once no healthy copy is left
        c.execute("UPDATE volume_copies SET last_check_ok = 0 WHERE volume_id = ?", (vols[1],))
        with pytest.raises(Exception, match="verified copy"):
            c.execute("UPDATE files SET rel_path = NULL WHERE id = ?", (fid,))


def test_04_upload_killed_while_finishing_is_recovered(cfg, tmp_path):
    p = make_jpeg(tmp_path / "IMG_3.JPG")
    data = p.read_bytes()
    with TestClient(create_app(cfg)) as client:
        a = Api(client, cfg, login(client, cfg))
        meta = "filename " + base64.b64encode(b"IMG_3.JPG").decode()
        r = a.post("/api/uploads", headers={"Upload-Length": str(len(data)), "Upload-Metadata": meta,
                                            "Tus-Resumable": "1.0.0"})
        uid = r.headers["location"].rsplit("/", 1)[1]
        (cfg.subdir("tmp") / "uploads" / f"{uid}.part").write_bytes(data)
        ex(cfg, "UPDATE uploads SET status='processing' WHERE id=?", uid)  # SIGKILL here
    with TestClient(create_app(cfg)) as client:
        a = Api(client, cfg, login(client, cfg))
        result = a.get(f"/api/uploads/{uid}/result").json()
        assert result["status"] == "new"
        assert a.item(result["item_id"])["sha256"] == hashlib.sha256(data).hexdigest()


def test_05_concurrent_patches_never_corrupt_the_file(tmp_path):
    cfg = Config(data_dir=tmp_path / "dados", workers=False, web_dir=tmp_path / "x")
    prepare(cfg)
    app = create_app(cfg)
    token = login(None, cfg)
    H = {"Authorization": f"Bearer {token}", "Tus-Resumable": "1.0.0"}
    data = os.urandom(300_000)
    first, rest = data[:100_000], data[100_000:]

    async def body(chunks, delay):
        for c in chunks:
            await asyncio.sleep(delay)
            yield c

    async def main():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            meta = "filename " + base64.b64encode(b"x.bin").decode()
            r = await c.post("/api/uploads", headers={**H, "Upload-Length": str(len(data)), "Upload-Metadata": meta})
            url = r.headers["location"]
            ph = {**H, "Content-Type": "application/offset+octet-stream"}
            p1 = asyncio.create_task(c.patch(url, headers={**ph, "Upload-Offset": "0"},
                                             content=body([first[:50_000], first[50_000:]], 0.2)))
            await asyncio.sleep(0.05)
            p2 = asyncio.create_task(c.patch(url, headers={**ph, "Upload-Offset": "100000"},
                                             content=body([rest[:100_000], rest[100_000:]], 0.3)))
            await p1
            await asyncio.sleep(0.05)
            p3 = asyncio.create_task(c.patch(url, headers={**ph, "Upload-Offset": "100000"},
                                             content=body([rest[:100_000], rest[100_000:]], 0.3)))
            return await p2, await p3

    asyncio.run(main())
    rows = q(cfg, "SELECT sha256 FROM items")
    assert [r[0] for r in rows] == [hashlib.sha256(data).hexdigest()]


def test_06_failed_live_photo_move_is_undone(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_0001.JPG")
    iid = api.upload(photo)["item_id"]
    ex(api.cfg, "UPDATE items SET live_photo_id='ABC' WHERE id=?", iid)
    assert api.upload(make_mov(tmp_path / "IMG_0001.MOV", "ABC"))["status"] == "attached"
    rows = dict(q(api.cfg, "SELECT role, rel_path FROM files WHERE item_id=?", iid))
    (api.cfg.data_dir / rows["live-video"]).unlink()
    assert api.act([iid], "keep")["failed"]
    assert (api.cfg.data_dir / rows["original"]).exists()  # photo moved back
    assert api.get(f"/api/items/{iid}/original").status_code == 200


def test_07_reconcile_checks_the_recorded_copy_before_deleting(api, tmp_path):
    p = make_jpeg(tmp_path / "IMG_9.JPG")
    iid = api.upload(p)["item_id"]
    rel = q(api.cfg, "SELECT rel_path FROM files WHERE item_id=?", iid)[0][0]
    stray = api.cfg.data_dir / "lixeira" / "stray.JPG"
    stray.write_bytes(p.read_bytes())
    (api.cfg.data_dir / rel).write_bytes(b"corrupted")
    rep = reconcile(api.cfg, api.client.app.state.ingestor)
    assert rep["repaired"] == 1 and rep["removed_copies"] == 0
    assert (api.cfg.data_dir / rel).read_bytes() == p.read_bytes()


def test_08_reconcile_keeps_a_freshly_reingested_live_video(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_0002.JPG")
    iid = api.upload(photo)["item_id"]
    ex(api.cfg, "UPDATE items SET live_photo_id='XYZ' WHERE id=?", iid)
    api.act([iid], "keep")
    mov = make_mov(tmp_path / "IMG_0002.MOV", "XYZ")
    (api.cfg.data_dir / "entrada" / "2024-05-01_1012_IMG_0002.MOV").write_bytes(mov.read_bytes())
    reconcile(api.cfg, api.client.app.state.ingestor)
    rel = q(api.cfg, "SELECT rel_path FROM files WHERE item_id=? AND role='live-video'", iid)[0][0]
    assert (api.cfg.data_dir / rel).read_bytes() == mov.read_bytes()


def test_09_stale_session_id_does_not_break_uploads(api, tmp_path):
    p = make_jpeg(tmp_path / "IMG_5.JPG")
    assert api.upload(p, session_id=999)["status"] == "new"
    res = api.post("/api/precheck", json={"session_id": 999, "entries": [{"key": "k", "sha256": sha(p)}]})
    assert res.status_code == 200 and res.json()["results"][0]["known"]


def test_10_local_mode_refuses_foreign_host_and_old_tokens_die(cfg):
    app = create_app(cfg)
    with TestClient(app, client=("127.0.0.1", 5555), base_url="http://evil.example:8765") as c:
        assert c.get("/api/stats").status_code == 401
    with TestClient(app, client=("127.0.0.1", 5555), base_url="http://127.0.0.1:8765") as c:
        assert c.get("/api/stats").status_code == 200  # the real local user still works
        assert c.post("/api/auth/app-token").status_code == 409  # no permanent tokens without a password
    from acervo import auth
    from acervo.catalog import transaction
    conn = db.connect(cfg.db_path)
    with transaction(conn):
        tok = auth.create_token(conn, "api", "antes da senha")
        auth.set_password(conn, "senha-forte-123")
    conn.close()
    with TestClient(app) as c:
        assert c.get("/api/stats", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_11_edited_version_gets_its_own_path_on_the_drive(api, tmp_path):
    from test_archive import archive_everything
    a = make_jpeg(tmp_path / "s1" / "IMG_7.JPG", color=(10, 10, 10))
    ia = api.upload(a)["item_id"]
    api.act([ia], "keep")
    first = archive_everything(api, tmp_path / "hd")
    b = make_jpeg(tmp_path / "s2" / "IMG_7.JPG", color=(200, 10, 10))
    ib = api.upload(b)["item_id"]
    api.act([ib], "keep")
    vid = first["volume"]["id"]
    plan = api.get("/api/archive/plan", params={"volume_id": vid}).json()["files"]
    assert plan[0]["rel_path"] != first["plan"]["files"][0]["rel_path"]
    res = api.post("/api/archive/verified", json={"volume_id": vid, "copies": [
        {"file_id": plan[0]["file_id"], "rel_path": plan[0]["rel_path"], "sha256": sha(b)}]}).json()
    assert res["accepted"] == [plan[0]["file_id"]]


def test_12_discarded_content_is_reported_apart(api, tmp_path):
    p = make_jpeg(tmp_path / "IMG_2.JPG")
    iid = api.upload(p)["item_id"]
    api.act([iid], "discard")
    s = api.post("/api/sessions", json={"source": "iphone-empty", "expected_count": 1}).json()
    api.upload(p, session_id=s["id"])
    sess = api.get(f"/api/sessions/{s['id']}").json()
    assert sess["discarded_count"] == 1 and "descartado antes" in sess["summary_text"]


def test_13_same_name_different_content_at_the_same_time(api, tmp_path, monkeypatch):
    real = ingest_mod.free_rel_path
    barrier = threading.Barrier(2)

    def slow(*a, **k):
        r = real(*a, **k)
        try:
            barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        return r

    monkeypatch.setattr(ingest_mod, "free_rel_path", slow)
    srcs = [make_jpeg(tmp_path / "a" / "IMG_1.JPG", color=(1, 2, 3)), make_jpeg(tmp_path / "b" / "IMG_1.JPG", color=(9, 9, 9))]
    ing = api.client.app.state.ingestor
    res, errs = [], []

    def run(src):
        t = api.cfg.subdir("tmp") / f"t-{src.parent.name}"
        t.write_bytes(src.read_bytes())
        try:
            res.append(ing.ingest(t, filename="IMG_1.JPG", source="web")["status"])
        except Exception as e:  # pragma: no cover
            errs.append(e)

    ts = [threading.Thread(target=run, args=(s,)) for s in srcs]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errs == [] and res == ["new", "new"]


def test_15_video_of_a_trashed_photo_is_not_purged_with_it(api, tmp_path):
    photo = make_jpeg(tmp_path / "IMG_0004.JPG")
    iid = api.upload(photo)["item_id"]
    ex(api.cfg, "UPDATE items SET live_photo_id='TTT' WHERE id=?", iid)
    api.act([iid], "discard")
    res = api.upload(make_mov(tmp_path / "IMG_0004.MOV", "TTT"))
    assert res["status"] == "new" and api.item(res["item_id"])["state"] == "inbox"


def test_16_empty_file_through_tus(api):
    meta = "filename " + base64.b64encode(b"vazio.txt").decode()
    r = api.post("/api/uploads", headers={"Upload-Length": "0", "Upload-Metadata": meta, "Tus-Resumable": "1.0.0"})
    result = api.get(r.headers["location"] + "/result").json()
    assert result["status"] == "new"


def test_18_thumbnails_survive_purge(api, tmp_path):
    from acervo.catalog import thumb_path
    p = make_jpeg(tmp_path / "IMG_T.JPG")
    iid = api.upload(p)["item_id"]
    api.run_jobs()
    api.act([iid], "discard")
    ex(api.cfg, "UPDATE items SET trashed_at='2000-01-01T00:00:00.000Z' WHERE id=?", iid)
    assert api.post("/api/trash/purge-expired").json()["purged"] == 1
    assert thumb_path(api.cfg, sha(p)).exists()


def test_19_partial_copies_are_cleaned(api, tmp_path):
    part = api.cfg.data_dir / "acervo" / "2024" / "x.JPG.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"half")
    assert reconcile(api.cfg, api.client.app.state.ingestor)["partials_removed"] == 1
    assert not part.exists()
