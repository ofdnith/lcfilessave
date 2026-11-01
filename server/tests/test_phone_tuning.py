"""Tuning for the Snapdragon 680 phone: heat pause, OCR on a reduced image,
in-memory perceptual hashes, and bringing items back from the retired microSD.

The card was retired on 01/11/2026. Items copied there before that come back to
the phone's own storage; that deletes the card copy, so every way it can be
interrupted is tested here (rule 3: nothing goes without a verified copy).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acervo import db, jobs, library, power, storage
from acervo.app import create_app
from acervo.config import Config, ConfigError, load_config
from acervo.ingest import reconcile
from acervo.jobs import Worker
from acervo.neardup import PhashIndex, np
from acervo.places import Gazetteer

from conftest import make_jpeg, put_on_card, sha


# --- heat ---------------------------------------------------------------------------------

def test_thermal_gate_pauses_and_resumes_with_margin():
    temps = iter([39.0, 40.0, 39.0, 37.5, 37.0, 36.0])
    gate = power.ThermalGate(40, read=lambda: next(temps))
    assert gate.too_hot() is False      # 39
    assert gate.too_hot() is True       # 40: pause
    assert gate.too_hot() is True       # 39: still hot (needs to cool 3 °C)
    assert gate.too_hot() is True       # 37.5
    assert gate.too_hot() is False      # 37: resumes
    assert gate.status() == {"temperature": 37.0, "max_temp_c": 40, "paused": False}


def test_thermal_gate_never_pauses_without_a_sensor():
    assert power.ThermalGate(40, read=lambda: None).too_hot() is False

    def broken():
        raise OSError("termux-api ausente")
    assert power.ThermalGate(40, read=broken).too_hot() is False


def test_worker_does_not_run_jobs_while_hot(api, tmp_path):
    api.upload(make_jpeg(tmp_path / "IMG_1.JPG"))
    w = Worker(api.cfg, api.client.app.state.exiftool, Gazetteer(api.cfg.subdir("geo")))
    w.thermal = power.ThermalGate(40, read=lambda: 45.0)
    t = threading.Thread(target=w._loop)
    t.start()
    try:
        t.join(timeout=1.0)
        c = db.connect(api.cfg.db_path)
        assert c.execute("SELECT count(*) FROM jobs WHERE status = 'pending'").fetchone()[0] > 0
        assert c.execute("SELECT count(*) FROM jobs WHERE status = 'done'").fetchone()[0] == 0
        c.close()
    finally:
        w._stop.set()
        t.join(timeout=5)
    assert w.thermal.status()["paused"] is True


def test_temperature_limit_is_validated():
    with pytest.raises(ConfigError):
        Config(max_temp_c=80).validate()


# --- OCR on the reduced image ---------------------------------------------------------------

def test_ocr_reads_a_reduced_copy_of_big_photos(api, tmp_path, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(power, "is_charging", lambda: True)
    seen = []

    def fake_ocr(path: Path) -> str:
        with Image.open(path) as im:
            seen.append((path.name, im.size, im.mode))
        return "nota fiscal pagamento recibo"
    monkeypatch.setattr(jobs, "ocr_image", fake_ocr)

    big = make_jpeg(tmp_path / "IMG_BIG.JPG", size=(4000, 3000))
    iid = api.upload(big)["item_id"]
    api.run_jobs()
    name, size, mode = seen[-1]
    assert name.startswith("ocr-") and max(size) <= 1600 and mode == "L"
    assert not list(api.cfg.subdir("tmp").glob("ocr-*"))  # temporary copy cleaned up
    found = api.get("/api/items", params={"view": "inbox", "q": "recibo"}).json()["items"]
    assert [i["id"] for i in found] == [iid]


def test_ocr_reads_small_images_directly(api, tmp_path, monkeypatch):
    monkeypatch.setattr(power, "is_charging", lambda: True)
    seen = []
    monkeypatch.setattr(jobs, "ocr_image", lambda p: seen.append(p.name) or "")
    api.upload(make_jpeg(tmp_path / "IMG_SMALL.JPG", size=(900, 300)))
    api.run_jobs()
    assert seen and not seen[-1].startswith("ocr-")


# --- in-memory perceptual hashes ------------------------------------------------------------

@pytest.mark.parametrize("use_numpy", [False, pytest.param(True, marks=pytest.mark.skipif(np is None, reason="sem numpy"))])
def test_phash_index_finds_the_same_neighbours_as_a_full_scan(use_numpy):
    import random
    from acervo.media import hamming
    rnd = random.Random(7)
    base = rnd.getrandbits(64)
    hashes = {i: rnd.getrandbits(64) for i in range(1, 3000)}
    for i in range(3000, 3010):  # a few close to `base`
        hashes[i] = base ^ (1 << rnd.randrange(64)) ^ (1 << rnd.randrange(64))
    signed = {i: h - (1 << 64) if h >= 1 << 63 else h for i, h in hashes.items()}  # as SQLite stores them
    idx = PhashIndex(use_numpy=use_numpy)
    for i, h in signed.items():
        idx.add(i, h)
    q = base - (1 << 64) if base >= 1 << 63 else base
    expected = sorted(i for i, h in signed.items() if hamming(h, q) <= 10)
    assert sorted(idx.near(q, 10)) == expected and len(expected) >= 10
    assert 3000 not in idx.near(q, 10, exclude=3000)
    idx.add(3000, ~q)  # regenerated thumbnail: replaced, not duplicated
    assert len(idx) == len(signed) and 3000 not in idx.near(q, 10)


def test_near_duplicates_ignore_items_discarded_after_indexing(api, tmp_path):
    from PIL import Image
    from acervo.media import hamming
    pa = make_jpeg(tmp_path / "IMG_A.JPG", size=(800, 600), pattern=4)
    pb = tmp_path / "IMG_B.JPG"  # the same picture, recompressed
    Image.open(pa).resize((400, 300)).save(pb, "JPEG", quality=40)
    a = api.upload(pa)["item_id"]
    api.run_jobs()
    api.act([a], "discard")
    b = api.upload(pb)["item_id"]
    w = Worker(api.cfg, api.client.app.state.exiftool, Gazetteer(api.cfg.subdir("geo")))
    c = db.connect(api.cfg.db_path)
    w.phashes.load(c)  # the index still holds the discarded one
    assert w.phashes.near(c.execute("SELECT phash FROM items WHERE id = ?", (a,)).fetchone()[0], 10)
    w.run_pending()
    ha, hb = (c.execute("SELECT phash FROM items WHERE id = ?", (i,)).fetchone()[0] for i in (a, b))
    assert hamming(ha, hb) <= 10, "as duas fotos precisam ser quase iguais para o teste valer"
    groups = c.execute("SELECT count(*) FROM suggestions WHERE kind = 'near-duplicate'").fetchone()[0]
    assert groups == 0, "um item na lixeira não pode virar sugestão"
    c.close()


# --- Entrada limit --------------------------------------------------------------------------

def test_uploads_stop_when_the_entrada_is_full(api, tmp_path, monkeypatch):
    from dataclasses import replace
    from acervo.api import uploads
    api.client.app.state.config = replace(api.cfg, inbox_max_gb=100)  # off by default since 01/11/2026
    monkeypatch.setattr(uploads, "inbox_bytes", lambda conn: 100 * 1_000_000_000)
    p = make_jpeg(tmp_path / "IMG_FULL.JPG")
    res = api.post("/api/upload", params={"source": "web"}, content=p.read_bytes(),
                   headers={"X-Filename": p.name, "Content-Type": "application/octet-stream"})
    assert res.status_code == 507 and "triagem" in res.json()["detail"]


def test_inbox_limit_in_config(tmp_path):
    conf = tmp_path / "acervo.toml"
    conf.write_text('inbox_max_gb = 90\nmax_temp_c = 42\n')
    cfg = load_config(conf)
    assert (cfg.inbox_max_gb, cfg.max_temp_c) == (90, 42)


def test_retired_options_in_an_old_config_are_ignored(tmp_path):
    conf = tmp_path / "acervo.toml"
    conf.write_text('sd_dir = "sd"\nsd_for_library = true\nremote_mode = "seguro"\n')
    cfg = load_config(conf)
    assert cfg.sd_dir is not None
    assert not hasattr(cfg, "sd_for_library") and not hasattr(cfg, "remote_mode")


# --- the retired microSD: items come back to the phone --------------------------------------

@pytest.fixture
def roomy(monkeypatch):
    """The phone has plenty of room, whatever the disk running the tests looks like."""
    monkeypatch.setattr(library, "disk_usage", lambda path: storage.DiskUsage(100 * 10**9, 30 * 10**9, 70 * 10**9))


def _files(cfg, item_id):
    c = db.connect(cfg.db_path)
    try:
        return [dict(r) for r in c.execute("SELECT * FROM files WHERE item_id = ?", (item_id,))]
    finally:
        c.close()


def _on_card(api, tmp_path, name="IMG_SD.JPG", pattern=1):
    src = make_jpeg(tmp_path / "in" / name, pattern=pattern)
    iid = api.upload(src)["item_id"]
    api.act([iid], "keep")
    put_on_card(api.cfg, iid)
    (f,) = _files(api.cfg, iid)
    assert f["root"] == "sd"
    return iid, sha(src)


def test_keep_never_goes_to_the_card(sd_api, tmp_path, roomy):
    src = make_jpeg(tmp_path / "in" / "IMG_K.JPG")
    iid = sd_api.upload(src)["item_id"]
    sd_api.act([iid], "keep")
    assert _files(sd_api.cfg, iid)[0]["root"] == "main"
    assert library.choose_root(sd_api.cfg, 10) == "main"


def test_card_items_come_back_verified(sd_api, tmp_path, roomy):
    cfg = sd_api.cfg
    iid, digest = _on_card(sd_api, tmp_path)
    (f,) = _files(cfg, iid)
    on_card = cfg.sd_dir / f["rel_path"]

    assert library.bring_back_from_card(cfg) == 1
    (f,) = _files(cfg, iid)
    inside = cfg.data_dir / f["rel_path"]
    assert f["root"] == "main" and f["rel_path"].startswith("acervo/2024/05/")
    assert sha(inside) == digest
    assert not on_card.exists()
    assert not list(cfg.data_dir.rglob("*.part"))
    c = db.connect(cfg.db_path)
    assert c.execute("SELECT count(*) FROM events WHERE action = 'from-sd' AND item_id = ?", (iid,)).fetchone()[0] == 1
    c.close()
    res = sd_api.get(f"/api/items/{iid}/original")
    assert res.status_code == 200 and res.content == inside.read_bytes()
    assert library.bring_back_from_card(cfg) == 0  # nothing left


def test_a_bad_copy_inside_keeps_the_card_one(sd_api, tmp_path, monkeypatch, roomy):
    cfg = sd_api.cfg
    iid, digest = _on_card(sd_api, tmp_path)
    (f,) = _files(cfg, iid)
    real = storage.sha256_file
    monkeypatch.setattr(storage, "sha256_file", lambda p: "0" * 64 if ".part" in p.name else real(p))
    assert library.bring_back_from_card(cfg) == 0
    assert _files(cfg, iid)[0]["root"] == "sd"
    assert sha(cfg.sd_dir / f["rel_path"]) == digest
    assert not list((cfg.data_dir / "acervo").rglob("*.JPG"))


def test_discarded_during_the_copy_leaves_no_orphan_inside(sd_api, tmp_path, monkeypatch, roomy):
    cfg = sd_api.cfg
    iid, digest = _on_card(sd_api, tmp_path)
    real_copy = library.copy_verified

    def copy_then_discard(src, dst, expected):
        real_copy(src, dst, expected)
        c = db.connect(cfg.db_path)
        try:
            library.discard(cfg, c, iid)
        finally:
            c.close()
    monkeypatch.setattr(library, "copy_verified", copy_then_discard)
    assert library.bring_back_from_card(cfg) == 0
    (f,) = _files(cfg, iid)
    assert f["rel_path"].startswith("lixeira/") and f["root"] == "sd"
    assert sha(cfg.sd_dir / f["rel_path"]) == digest
    assert not list((cfg.data_dir / "acervo").rglob("*.JPG"))


def test_killed_after_the_copy_before_the_switch(sd_api, tmp_path, roomy):
    """Process dies with the copy inside but the catalog still pointing to the card:
    the inside copy is redundant and reconcile removes it; the card copy is untouched."""
    cfg = sd_api.cfg
    iid, digest = _on_card(sd_api, tmp_path)
    (f,) = _files(cfg, iid)
    storage.copy_verified(cfg.sd_dir / f["rel_path"], cfg.data_dir / f["rel_path"], digest)
    rep = reconcile(cfg, sd_api.client.app.state.ingestor)
    assert rep["removed_copies"] == 1
    assert not (cfg.data_dir / f["rel_path"]).exists()
    assert sha(cfg.sd_dir / f["rel_path"]) == digest
    assert _files(cfg, iid)[0]["root"] == "sd"


def test_killed_after_the_switch_before_deleting_the_card_copy(sd_api, tmp_path, roomy):
    cfg = sd_api.cfg
    iid, digest = _on_card(sd_api, tmp_path)
    (before,) = _files(cfg, iid)
    leftover = cfg.sd_dir / before["rel_path"]
    keep_bytes = leftover.read_bytes()
    library.bring_back_from_card(cfg)
    leftover.write_bytes(keep_bytes)  # as if the delete never happened
    rep = reconcile(cfg, sd_api.client.app.state.ingestor)
    assert rep["removed_copies"] == 1 and not leftover.exists()
    (f,) = _files(cfg, iid)
    assert f["root"] == "main" and sha(cfg.data_dir / f["rel_path"]) == digest


def test_nothing_comes_back_during_a_migration(sd_api, tmp_path, monkeypatch, roomy):
    from acervo.catalog import set_setting
    cfg = sd_api.cfg
    iid, digest = _on_card(sd_api, tmp_path)
    c = db.connect(cfg.db_path)
    set_setting(c, "migration_active", "1")
    assert library.bring_back_from_card(cfg) == 0
    set_setting(c, "migration_active", "")
    real_copy = library.copy_verified

    def copy_then_freeze(src, dst, expected):
        real_copy(src, dst, expected)
        set_setting(c, "migration_active", "1")
    monkeypatch.setattr(library, "copy_verified", copy_then_freeze)
    assert library.bring_back_from_card(cfg) == 0
    (f,) = _files(cfg, iid)
    assert f["root"] == "sd" and sha(cfg.sd_dir / f["rel_path"]) == digest
    assert not list((cfg.data_dir / "acervo").rglob("*.JPG"))
    c.close()


def test_no_room_inside_or_missing_card_leaves_items_on_the_card(sd_api, tmp_path, monkeypatch, roomy):
    cfg = sd_api.cfg
    iid, _ = _on_card(sd_api, tmp_path)
    with monkeypatch.context() as m:
        m.setattr(library, "internal_has_room", lambda cfg, size: False)
        assert library.bring_back_from_card(cfg) == 0
    gone = Config(**{**cfg.__dict__, "sd_dir": tmp_path / "cartao-removido"})
    assert library.bring_back_from_card(gone) == 0
    assert _files(cfg, iid)[0]["root"] == "sd"
    assert library.bring_back_from_card(cfg) == 1  # card back, room inside: it catches up


def test_items_still_on_the_card_can_be_discarded_and_restored(sd_api, tmp_path, roomy):
    cfg = sd_api.cfg
    iid, digest = _on_card(sd_api, tmp_path)
    sd_api.act([iid], "discard")
    (f,) = _files(cfg, iid)
    assert f["root"] == "sd" and f["rel_path"].startswith("lixeira/")
    sd_api.act([iid], "restore")
    (f,) = _files(cfg, iid)
    assert f["root"] == "sd" and sha(cfg.sd_dir / f["rel_path"]) == digest
