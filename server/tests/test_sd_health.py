"""Entrada reminder, microSD health checks and the offline browser on the card.

A damaged copy on the card must stop counting as "stored safely", so the
iPhone sends it again and the upload repairs it; the damaged bytes are set
aside, never deleted. A card removed in the middle of a check must not be
taken as "every file is broken".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from acervo import db, library, push, sdcard
from acervo.catalog import iso_in, set_setting
from acervo.config import Config, ConfigError
from acervo.ingest import reconcile
from acervo.jobs import Worker
from acervo.places import Gazetteer

from conftest import make_jpeg, sha


def _conn(api):
    return db.connect(api.cfg.db_path)


def _file(api, item_id):
    c = _conn(api)
    try:
        return dict(c.execute("SELECT * FROM files WHERE item_id = ? AND role = 'original'", (item_id,)).fetchone())
    finally:
        c.close()


def _on_card(api, tmp_path, name="IMG_SD.JPG", pattern=1, created_at=None):
    src = make_jpeg(tmp_path / "in" / name, pattern=pattern)
    iid = api.upload(src, created_at=created_at)["item_id"]
    api.act([iid], "keep")
    assert library.migrate_to_sd(api.cfg) == 1
    return iid, src


def _worker(api):
    return Worker(api.cfg, api.client.app.state.exiftool, Gazetteer(api.cfg.subdir("geo")))


# --- Entrada reminder ---------------------------------------------------------------------

def test_no_reminder_for_a_fresh_small_entrada(api, tmp_path):
    api.upload(make_jpeg(tmp_path / "IMG_1.JPG"))
    s = api.get("/api/stats").json()["storage"]
    assert s["inbox_reminder"] is None and s["inbox_waiting_days"] == 0


def test_reminder_after_days_without_triage(api, tmp_path):
    iid = api.upload(make_jpeg(tmp_path / "IMG_OLD.JPG"))["item_id"]
    c = _conn(api)
    c.execute("UPDATE items SET uploaded_at = ? WHERE id = ?", (iso_in(-8.2), iid))
    c.close()
    s = api.get("/api/stats").json()["storage"]
    assert s["inbox_reminder"]["reasons"] == ["dias"] and s["inbox_reminder"]["days"] == 8
    api.act([iid], "keep")
    assert api.get("/api/stats").json()["storage"]["inbox_reminder"] is None


def test_reminder_when_the_entrada_passes_5_gb(api, tmp_path, monkeypatch):
    api.upload(make_jpeg(tmp_path / "IMG_BIG.JPG"))
    monkeypatch.setattr(library, "inbox_bytes", lambda conn: 6_000_000_000)
    r = api.get("/api/stats").json()["storage"]["inbox_reminder"]
    assert r["reasons"] == ["tamanho"] and r["bytes"] == 6_000_000_000
    assert "6,0 GB na Entrada" in library.inbox_reminder_text(r)


def test_reminder_can_be_switched_off(tmp_path):
    c = db.connect(tmp_path / "c.db")
    db.migrate(c)
    from conftest import insert_item
    insert_item(c, uploaded_at=iso_in(-40), state="inbox")
    assert library.storage_summary(Config(data_dir=tmp_path, workers=False), c)["inbox_reminder"]
    cfg = Config(data_dir=tmp_path, workers=False, inbox_alert_days=0, inbox_alert_gb=0)
    assert library.storage_summary(cfg, c)["inbox_reminder"] is None
    with pytest.raises(ConfigError):
        Config(inbox_alert_days=-1).validate()


def test_reminder_push_at_most_every_three_days(api, tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "notify", lambda cfg, topic, *a: sent.append(topic))
    iid = api.upload(make_jpeg(tmp_path / "IMG_P.JPG"))["item_id"]
    c = _conn(api)
    c.execute("UPDATE items SET uploaded_at = ? WHERE id = ?", (iso_in(-10), iid))
    w = _worker(api)
    w._notices(c, "2026-10-29")
    w._notices(c, "2026-10-30")
    assert sent.count("entrada") == 1
    set_setting(c, "notice_inbox_at", iso_in(-4))
    w._notices(c, "2026-11-02")
    assert sent.count("entrada") == 2
    c.close()


# --- microSD health -----------------------------------------------------------------------

def test_healthy_card_files_pass(sd_api, tmp_path):
    iid, _ = _on_card(sd_api, tmp_path)
    c = _conn(sd_api)
    report = sdcard.check_files(sd_api.cfg, c)
    assert report == {"checked": 1, "damaged": []}
    assert c.execute("SELECT check_ok FROM files WHERE item_id = ?", (iid,)).fetchone()[0] == 1
    assert sdcard.health(sd_api.cfg, c)["damaged"] == 0
    c.close()


def test_damaged_file_is_flagged_and_reported(sd_api, tmp_path):
    iid, _ = _on_card(sd_api, tmp_path)
    f = _file(sd_api, iid)
    (sd_api.cfg.sd_dir / f["rel_path"]).write_bytes(b"bits trocados pelo cartao")
    c = _conn(sd_api)
    report = sdcard.check_files(sd_api.cfg, c)
    assert report["damaged"] == [iid]
    h = sdcard.health(sd_api.cfg, c)
    assert h["damaged"] == 1 and h["damaged_names"] == ["IMG_SD.JPG"]
    assert c.execute("SELECT count(*) FROM events WHERE action = 'sd-check-failed'").fetchone()[0] == 1
    c.close()
    health = sd_api.client.get("/api/health").json()
    assert any("cartão microSD falhou" in p for p in health["problems"])


def test_missing_file_on_a_present_card_is_damaged(sd_api, tmp_path):
    iid, _ = _on_card(sd_api, tmp_path)
    (sd_api.cfg.sd_dir / _file(sd_api, iid)["rel_path"]).unlink()
    c = _conn(sd_api)
    assert sdcard.check_files(sd_api.cfg, c)["damaged"] == [iid]
    c.close()


def test_card_removed_during_the_check_marks_nothing(sd_api, tmp_path, monkeypatch):
    a, _ = _on_card(sd_api, tmp_path, "IMG_A.JPG", pattern=1)
    b, _ = _on_card(sd_api, tmp_path, "IMG_B.JPG", pattern=2)
    c = _conn(sd_api)
    c.execute("UPDATE files SET checked_at = NULL, check_ok = NULL")
    card = sd_api.cfg.sd_dir
    hidden = card.with_name("sd-fora")

    def card_pulled(path):
        card.rename(hidden)  # the card leaves the phone while being read
        raise OSError("I/O error")
    monkeypatch.setattr(sdcard, "sha256_file", card_pulled)
    report = sdcard.check_files(sd_api.cfg, c)
    hidden.rename(card)
    assert report["damaged"] == []
    assert c.execute("SELECT count(*) FROM files WHERE check_ok = 0").fetchone()[0] == 0
    c.close()


def test_daily_slice_checks_oldest_first(sd_api, tmp_path):
    ids = [_on_card(sd_api, tmp_path, f"IMG_{n}.JPG", pattern=n)[0] for n in (1, 2, 3)]
    c = _conn(sd_api)
    c.execute("UPDATE files SET checked_at = ? WHERE item_id = ?", (iso_in(-1), ids[0]))
    c.execute("UPDATE files SET checked_at = ? WHERE item_id = ?", (iso_in(-20), ids[1]))
    c.execute("UPDATE files SET checked_at = NULL WHERE item_id = ?", (ids[2],))
    sdcard.check_files(sd_api.cfg, c, limit=2)
    fresh = {r[0]: r[1] for r in c.execute("SELECT item_id, checked_at FROM files")}
    assert fresh[ids[0]] < iso_in(-0.5)            # recent: left for later
    assert fresh[ids[1]] > iso_in(-0.01) and fresh[ids[2]] > iso_in(-0.01)
    c.close()


def test_slice_covers_the_card_in_30_days():
    assert sdcard.SD_CHECK_CYCLE_DAYS == 30


def test_copy_to_card_counts_as_a_check(sd_api, tmp_path):
    iid, _ = _on_card(sd_api, tmp_path)
    f = _file(sd_api, iid)
    assert f["check_ok"] == 1 and f["checked_at"] is not None


def test_damaged_copy_is_asked_again_and_the_upload_repairs_it(sd_api, tmp_path):
    iid, src = _on_card(sd_api, tmp_path, created_at=1714569153000)
    f = _file(sd_api, iid)
    on_card = sd_api.cfg.sd_dir / f["rel_path"]
    on_card.write_bytes(b"estragado")
    c = _conn(sd_api)
    sdcard.check_files(sd_api.cfg, c)
    c.close()

    entries = [{"key": "by-hash", "sha256": sha(src)},
               {"key": "by-fingerprint", "name": src.name, "created_at": 1714569153000, "size": src.stat().st_size}]
    res = sd_api.post("/api/precheck", json={"entries": entries}).json()["results"]
    assert [r["known"] for r in res] == [False, False], "o iPhone precisa mandar de novo"

    out = sd_api.upload(src)
    assert out["status"] == "restored"
    assert sha(on_card) == sha(src)
    quarantined = list((sd_api.cfg.sd_dir / "corrompidos").iterdir())
    assert len(quarantined) == 1 and quarantined[0].read_bytes() == b"estragado"  # set aside, not deleted
    assert _file(sd_api, iid)["check_ok"] == 1
    res = sd_api.post("/api/precheck", json={"entries": entries}).json()["results"]
    assert [r["known"] for r in res] == [True, True]


def test_reconcile_repairs_a_card_copy_in_place(sd_api, tmp_path):
    """A good copy found on disk replaces a damaged one; the damaged one is set
    aside on the card itself (a rename), not moved across storages."""
    iid, src = _on_card(sd_api, tmp_path)
    f = _file(sd_api, iid)
    recorded = sd_api.cfg.sd_dir / f["rel_path"]
    recorded.write_bytes(b"estragado")
    (recorded.parent / "copia-boa.jpg").write_bytes(src.read_bytes())
    rep = reconcile(sd_api.cfg, sd_api.client.app.state.ingestor)
    assert rep["repaired"] == 1
    assert sha(recorded) == sha(src)
    assert [p.read_bytes() for p in (sd_api.cfg.sd_dir / "corrompidos").iterdir()] == [b"estragado"]


def test_maintenance_checks_once_a_day_and_notifies(sd_api, tmp_path, monkeypatch):
    iid, _ = _on_card(sd_api, tmp_path)
    (sd_api.cfg.sd_dir / _file(sd_api, iid)["rel_path"]).write_bytes(b"x")
    sent = []
    c = _conn(sd_api)
    sdcard.maintain(sd_api.cfg, c, "2026-10-29", notify=lambda topic, *a: sent.append(topic))
    sdcard.maintain(sd_api.cfg, c, "2026-10-29", notify=lambda topic, *a: sent.append(topic))
    assert sent == ["cartao"]
    c.close()


def test_new_push_topics_reach_existing_subscribers(tmp_path):
    from acervo.db import load_migrations, migrate
    c = db.connect(tmp_path / "c.db")
    migrate(c, [m for m in load_migrations() if m.version <= 4])
    c.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, topics) VALUES ('https://x', 'k', 'a', '[\"espaco\"]')")
    migrate(c)
    import json
    assert json.loads(c.execute("SELECT topics FROM push_subscriptions").fetchone()[0]) == ["espaco", "entrada", "cartao"]
    assert {"entrada", "cartao"} <= set(push.TOPICS)


# --- offline browser on the card ----------------------------------------------------------

def test_card_gets_an_offline_browser_with_thumbnails(sd_api, tmp_path):
    iid, src = _on_card(sd_api, tmp_path)
    sd_api.run_jobs()  # thumbnails
    c = _conn(sd_api)
    assert sdcard.write_browser(sd_api.cfg, c) == 1
    card = sd_api.cfg.sd_dir
    page = (card / "ABRIR-ACERVO.html").read_text("utf-8")
    f = _file(sd_api, iid)
    assert "Cartão microSD" in page and "IMG_SD.JPG" in page and f["rel_path"] in page
    assert (card / f["rel_path"]).is_file()  # the link in the page is relative to the card
    item_sha = c.execute("SELECT sha256 FROM items WHERE id = ?", (iid,)).fetchone()[0]
    thumb = card / ".acervo" / "miniaturas" / f"{item_sha}.webp"
    assert thumb.is_file()

    sd_api.act([iid], "discard")  # left the Acervo: its thumbnail leaves the card too
    assert sdcard.write_browser(sd_api.cfg, c) == 0
    assert not thumb.exists()
    assert not list(card.glob("*.tmp"))
    c.close()


def test_browser_is_rewritten_only_when_the_card_changes(sd_api, tmp_path, monkeypatch):
    _on_card(sd_api, tmp_path, "IMG_1.JPG", pattern=1)
    writes = []
    real = sdcard.write_browser
    monkeypatch.setattr(sdcard, "write_browser", lambda cfg, conn: writes.append(1) or real(cfg, conn))
    c = _conn(sd_api)
    sdcard.maintain(sd_api.cfg, c, "2026-10-29")
    sdcard.maintain(sd_api.cfg, c, "2026-10-29")
    assert len(writes) == 1
    _on_card(sd_api, tmp_path, "IMG_2.JPG", pattern=2)
    sdcard.maintain(sd_api.cfg, c, "2026-10-29")
    assert len(writes) == 1  # changed, but written less than 30 minutes ago
    set_setting(c, "sd_browser_at", iso_in(-1))
    sdcard.maintain(sd_api.cfg, c, "2026-10-29")
    assert len(writes) == 2
    assert "IMG_2.JPG" in (sd_api.cfg.sd_dir / "ABRIR-ACERVO.html").read_text("utf-8")
    c.close()


def test_browser_page_cannot_be_broken_by_a_file_name(sd_api, tmp_path):
    _on_card(sd_api, tmp_path, "x</script><script>alert(1).jpg")
    c = _conn(sd_api)
    sdcard.write_browser(sd_api.cfg, c)
    page = (sd_api.cfg.sd_dir / "ABRIR-ACERVO.html").read_text("utf-8")
    assert "</script><script>alert" not in page
    c.close()


# --- the daily backup reaches back for damaged photos -------------------------------------

def _damaged_on_card(api, tmp_path, source):
    src = make_jpeg(tmp_path / "in" / f"IMG_{source}.JPG", date="2024:05:01 10:12:33", offset="-03:00")
    iid = api.upload(src, source=source)["item_id"]
    api.act([iid], "keep")
    library.migrate_to_sd(api.cfg)
    (api.cfg.sd_dir / _file(api, iid)["rel_path"]).write_bytes(b"estragado")
    c = _conn(api)
    sdcard.check_files(api.cfg, c)
    return iid, c


def test_daily_backup_reaches_back_for_a_damaged_iphone_photo(sd_api, tmp_path):
    normal = sd_api.get("/api/daily").json()["since"]
    iid, c = _damaged_on_card(sd_api, tmp_path, "iphone-manual")
    d = sd_api.get("/api/daily").json()
    assert d["repairing"] is True
    assert d["since"] == "2024-05-01T12:12:33.000Z"  # 10:12:33 -03:00, one hour earlier, in UTC
    # Gave the iPhone a few days: back to normal, so backups do not re-send old photos forever.
    c.execute("UPDATE files SET checked_at = ? WHERE item_id = ?", (iso_in(-4), iid))
    d = sd_api.get("/api/daily").json()
    assert d["repairing"] is False and d["since"][:10] == normal[:10]
    c.close()


def test_no_reach_back_for_photos_not_from_the_iphone(sd_api, tmp_path):
    for source in ("web", "iphone-empty"):  # from the Mac, or already emptied from the iPhone
        _, c = _damaged_on_card(sd_api, tmp_path, source)
        c.close()
    assert sd_api.get("/api/daily").json()["repairing"] is False
