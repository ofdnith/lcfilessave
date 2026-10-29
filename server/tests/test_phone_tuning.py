"""Tuning for the Snapdragon 680 phone: heat pause, OCR on a reduced image,
in-memory perceptual hashes, and the microSD as the home of the Acervo.

The microSD flow deletes the internal copy of a file, so every way it can be
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

from conftest import make_jpeg, sha


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
    from acervo.api import uploads
    monkeypatch.setattr(uploads, "inbox_bytes", lambda conn: 100 * 1_000_000_000)
    p = make_jpeg(tmp_path / "IMG_FULL.JPG")
    res = api.post("/api/upload", params={"source": "web"}, content=p.read_bytes(),
                   headers={"X-Filename": p.name, "Content-Type": "application/octet-stream"})
    assert res.status_code == 507 and "triagem" in res.json()["detail"]


def test_inbox_limit_in_config(tmp_path):
    conf = tmp_path / "acervo.toml"
    conf.write_text('inbox_max_gb = 90\nsd_dir = "sd"\nsd_for_library = true\nmax_temp_c = 42\n')
    cfg = load_config(conf)
    assert (cfg.inbox_max_gb, cfg.sd_for_library, cfg.max_temp_c) == (90, True, 42)
    conf.write_text("sd_for_library = true\n")
    with pytest.raises(ConfigError):
        load_config(conf)


# --- microSD as the home of the Acervo ------------------------------------------------------

def _files(cfg, item_id):
    c = db.connect(cfg.db_path)
    try:
        return [dict(r) for r in c.execute("SELECT * FROM files WHERE item_id = ?", (item_id,))]
    finally:
        c.close()


def _kept(api, tmp_path, name="IMG_SD.JPG", pattern=1):
    src = make_jpeg(tmp_path / "in" / name, pattern=pattern)
    iid = api.upload(src)["item_id"]
    api.act([iid], "keep")
    return iid, sha(src)


def test_keep_is_instant_and_the_card_gets_a_verified_copy(sd_api, tmp_path):
    cfg = sd_api.cfg
    iid, digest = _kept(sd_api, tmp_path)
    (f,) = _files(cfg, iid)
    assert f["root"] == "main"  # triage does not wait on the card
    internal = cfg.data_dir / f["rel_path"]

    assert library.migrate_to_sd(cfg) == 1
    (f,) = _files(cfg, iid)
    on_card = cfg.sd_dir / f["rel_path"]
    assert f["root"] == "sd" and f["rel_path"].startswith("acervo/2024/05/")
    assert sha(on_card) == digest
    assert not internal.exists()
    assert not list(cfg.sd_dir.rglob("*.part"))
    c = db.connect(cfg.db_path)
    assert c.execute("SELECT count(*) FROM events WHERE action = 'to-sd' AND item_id = ?", (iid,)).fetchone()[0] == 1
    c.close()
    res = sd_api.get(f"/api/items/{iid}/original")
    assert res.status_code == 200 and res.content == on_card.read_bytes()  # served from the card
    assert library.migrate_to_sd(cfg) == 0  # nothing left


def test_entrada_never_goes_to_the_card(sd_api, tmp_path):
    iid = sd_api.upload(make_jpeg(tmp_path / "IMG_IN.JPG"))["item_id"]
    assert library.migrate_to_sd(sd_api.cfg) == 0
    assert _files(sd_api.cfg, iid)[0]["root"] == "main"


def test_a_bad_copy_on_the_card_keeps_the_internal_one(sd_api, tmp_path, monkeypatch):
    cfg = sd_api.cfg
    iid, digest = _kept(sd_api, tmp_path)
    (f,) = _files(cfg, iid)
    real = storage.sha256_file
    monkeypatch.setattr(storage, "sha256_file", lambda p: "0" * 64 if ".part" in p.name else real(p))
    assert library.migrate_to_sd(cfg) == 0
    assert _files(cfg, iid)[0]["root"] == "main"
    assert sha(cfg.data_dir / f["rel_path"]) == digest
    assert not [p for p in cfg.sd_dir.rglob("*") if p.is_file()]


def test_discarded_during_the_copy_leaves_no_orphan_on_the_card(sd_api, tmp_path, monkeypatch):
    cfg = sd_api.cfg
    iid, digest = _kept(sd_api, tmp_path)
    real_copy = library.copy_verified

    def copy_then_discard(src, dst, expected):
        real_copy(src, dst, expected)
        c = db.connect(cfg.db_path)
        try:
            library.discard(cfg, c, iid)
        finally:
            c.close()
    monkeypatch.setattr(library, "copy_verified", copy_then_discard)
    assert library.migrate_to_sd(cfg) == 0
    (f,) = _files(cfg, iid)
    assert f["rel_path"].startswith("lixeira/") and f["root"] == "main"
    assert sha(cfg.data_dir / f["rel_path"]) == digest
    assert not [p for p in cfg.sd_dir.rglob("*") if p.is_file()]


def test_killed_after_the_copy_before_the_switch(sd_api, tmp_path):
    """Process dies with the copy on the card but the catalog still pointing inside:
    the card copy is redundant and reconcile removes it; the original is untouched."""
    cfg = sd_api.cfg
    iid, digest = _kept(sd_api, tmp_path)
    (f,) = _files(cfg, iid)
    storage.copy_verified(cfg.data_dir / f["rel_path"], cfg.sd_dir / f["rel_path"], digest)
    rep = reconcile(cfg, sd_api.client.app.state.ingestor)
    assert rep["removed_copies"] == 1
    assert not (cfg.sd_dir / f["rel_path"]).exists()
    assert sha(cfg.data_dir / f["rel_path"]) == digest
    assert _files(cfg, iid)[0]["root"] == "main"


def test_killed_after_the_switch_before_deleting_the_internal_copy(sd_api, tmp_path):
    cfg = sd_api.cfg
    iid, digest = _kept(sd_api, tmp_path)
    (before,) = _files(cfg, iid)
    leftover = cfg.data_dir / before["rel_path"]
    keep_bytes = leftover.read_bytes()
    library.migrate_to_sd(cfg)
    leftover.write_bytes(keep_bytes)  # as if the delete never happened
    rep = reconcile(cfg, sd_api.client.app.state.ingestor)
    assert rep["removed_copies"] == 1 and not leftover.exists()
    (f,) = _files(cfg, iid)
    assert f["root"] == "sd" and sha(cfg.sd_dir / f["rel_path"]) == digest


def test_nothing_moves_to_the_card_during_a_migration(sd_api, tmp_path, monkeypatch):
    from acervo.catalog import set_setting
    cfg = sd_api.cfg
    iid, digest = _kept(sd_api, tmp_path)
    c = db.connect(cfg.db_path)
    set_setting(c, "migration_active", "1")
    assert library.migrate_to_sd(cfg) == 0
    # A copy already running when the migration starts must not switch either.
    set_setting(c, "migration_active", "")
    real_copy = library.copy_verified

    def copy_then_freeze(src, dst, expected):
        real_copy(src, dst, expected)
        set_setting(c, "migration_active", "1")
    monkeypatch.setattr(library, "copy_verified", copy_then_freeze)
    assert library.migrate_to_sd(cfg) == 0
    (f,) = _files(cfg, iid)
    assert f["root"] == "main" and sha(cfg.data_dir / f["rel_path"]) == digest
    assert not [p for p in cfg.sd_dir.rglob("*") if p.is_file()]
    c.close()


def test_full_or_missing_card_keeps_everything_inside(sd_api, tmp_path, monkeypatch):
    cfg = sd_api.cfg
    iid, _ = _kept(sd_api, tmp_path)
    monkeypatch.setattr(library, "sd_has_room", lambda cfg, size: False)
    assert library.migrate_to_sd(cfg) == 0
    monkeypatch.undo()
    gone = Config(**{**cfg.__dict__, "sd_dir": tmp_path / "cartao-removido"})
    assert library.migrate_to_sd(gone) == 0
    assert _files(cfg, iid)[0]["root"] == "main"
    assert library.migrate_to_sd(cfg) == 1  # card back with room: it catches up


def test_items_on_the_card_can_be_discarded_and_restored(sd_api, tmp_path):
    cfg = sd_api.cfg
    iid, digest = _kept(sd_api, tmp_path)
    library.migrate_to_sd(cfg)
    sd_api.act([iid], "discard")
    (f,) = _files(cfg, iid)
    assert f["root"] == "sd" and f["rel_path"].startswith("lixeira/")
    sd_api.act([iid], "restore")
    (f,) = _files(cfg, iid)
    assert f["root"] == "sd" and sha(cfg.sd_dir / f["rel_path"]) == digest


def test_card_holds_a_catalog_copy_and_instructions(sd_api, tmp_path):
    cfg = sd_api.cfg
    _kept(sd_api, tmp_path)
    w = Worker(cfg, sd_api.client.app.state.exiftool, Gazetteer(cfg.subdir("geo")))
    w.maintenance()
    rescue = cfg.sd_dir / jobs.SD_RESCUE_DIR
    copies = list(rescue.glob("catalogo-*.db"))
    assert len(copies) == 1 and (rescue / "LEIA-ME.txt").is_file()
    c = db.connect(copies[0])
    assert c.execute("SELECT count(*) FROM items").fetchone()[0] == 1
    c.close()


def test_stats_show_entrada_and_card(sd_api, tmp_path):
    iid, _ = _kept(sd_api, tmp_path)
    s = sd_api.get("/api/stats").json()["storage"]
    assert s["inbox_max_bytes"] == 100 * 1_000_000_000
    assert s["sd"]["present"] and s["sd"]["pending_bytes"] > 0 and s["sd"]["library_bytes"] == 0
    library.migrate_to_sd(sd_api.cfg)
    s = sd_api.get("/api/stats").json()["storage"]
    assert s["sd"]["pending_bytes"] == 0 and s["sd"]["library_bytes"] > 0
    h = sd_api.client.get("/api/health").json()
    assert h["storage"]["sd"]["present"] is True
