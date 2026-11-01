"""Alerts (app banners + iPhone notifications) since the microSD was retired.

The phone's own storage now holds the Entrada and the Acervo until a batch goes
to an external storage, so the alerts are: space on the phone, a batch waiting
for a storage, the Entrada waiting for triage, the daily backup, and — only
while old items are still stranded on it — the retired card.
"""

from __future__ import annotations

import json

import pytest

from acervo import db, library, push
from acervo.catalog import iso_in, set_setting
from acervo.config import Config, ConfigError
from acervo.jobs import Worker
from acervo.places import Gazetteer
from acervo.storage import DiskUsage

from conftest import make_jpeg, put_on_card


def _conn(api):
    return db.connect(api.cfg.db_path)


def _worker(api):
    return Worker(api.cfg, api.client.app.state.exiftool, Gazetteer(api.cfg.subdir("geo")))


def _ids(api):
    return [a["id"] for a in api.get("/api/stats").json()["alerts"]]


def _disk(monkeypatch, used_pct, free_gb=20):
    total = 100_000_000_000
    used = int(total * used_pct / 100)
    monkeypatch.setattr(library, "disk_usage", lambda path: DiskUsage(total, used, free_gb * 1_000_000_000))


# --- Entrada reminder ---------------------------------------------------------------------

def test_no_reminder_for_a_fresh_small_entrada(api, tmp_path):
    api.upload(make_jpeg(tmp_path / "IMG_1.JPG"))
    s = api.get("/api/stats").json()["storage"]
    assert s["inbox_reminder"] is None and s["inbox_waiting_days"] == 0
    assert "entrada" not in _ids(api)


def test_reminder_after_days_without_triage(api, tmp_path):
    iid = api.upload(make_jpeg(tmp_path / "IMG_OLD.JPG"))["item_id"]
    c = _conn(api)
    c.execute("UPDATE items SET uploaded_at = ? WHERE id = ?", (iso_in(-8.2), iid))
    c.close()
    s = api.get("/api/stats").json()["storage"]
    assert s["inbox_reminder"]["reasons"] == ["dias"] and s["inbox_reminder"]["days"] == 8
    assert "entrada" in _ids(api)
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


def test_entrada_has_no_size_limit_by_default():
    assert Config().inbox_max_gb == 0


# --- batch waiting for an external storage ------------------------------------------------

def test_batch_alert_by_age(api, tmp_path):
    iid = api.upload(make_jpeg(tmp_path / "IMG_K.JPG"))["item_id"]
    api.act([iid], "keep")
    assert "lote" not in _ids(api)  # small and fresh: nothing to do yet
    c = _conn(api)
    c.execute("UPDATE items SET uploaded_at = ? WHERE id = ?", (iso_in(-15), iid))
    c.close()
    alert = next(a for a in api.get("/api/stats").json()["alerts"] if a["id"] == "lote")
    assert "15 dias" in alert["text"] and "só existem no celular" in alert["text"]
    assert alert["href"] == "/#/dispositivos" and "armazenamento" in alert["title"]


def test_batch_alert_by_size(api, tmp_path, monkeypatch):
    iid = api.upload(make_jpeg(tmp_path / "IMG_S.JPG"))["item_id"]
    api.act([iid], "keep")
    monkeypatch.setattr(library, "pending_archive", lambda cfg, conn: {"bytes": 6_000_000_000, "oldest_days": 1})
    assert "lote" in _ids(api)


def test_batch_alert_by_age_can_be_switched_off(tmp_path):
    c = db.connect(tmp_path / "c.db")
    db.migrate(c)
    from conftest import insert_file, insert_item
    iid = insert_item(c, uploaded_at=iso_in(-40), state="library")
    insert_file(c, iid, rel_path="acervo/2024/05/fotos/x.heic")
    on = Config(data_dir=tmp_path, workers=False)
    off = Config(data_dir=tmp_path, workers=False, archive_alert_days=0)
    assert "lote" in [a["id"] for a in library.alerts(on, c)]
    assert "lote" not in [a["id"] for a in library.alerts(off, c)]
    with pytest.raises(ConfigError):
        Config(archive_alert_days=-1).validate()


# --- space on the phone -------------------------------------------------------------------

def test_space_alert_points_to_the_batch_when_there_is_one(api, tmp_path, monkeypatch):
    _disk(monkeypatch, 85)
    a = next(a for a in api.get("/api/stats").json()["alerts"] if a["id"] == "espaco")
    assert a["level"] == "warn" and a["href"] == "/#/entrada"  # nothing kept yet: triage first
    iid = api.upload(make_jpeg(tmp_path / "IMG_E.JPG"))["item_id"]
    api.act([iid], "keep")
    a = next(a for a in api.get("/api/stats").json()["alerts"] if a["id"] == "espaco")
    assert a["href"] == "/#/dispositivos" and "armazenamento" in a["text"]


def test_space_alert_turns_critical(api, monkeypatch):
    _disk(monkeypatch, 96, free_gb=2)
    alerts = api.get("/api/stats").json()["alerts"]
    assert alerts[0]["id"] == "espaco" and alerts[0]["level"] == "danger"
    assert "vão parar" in alerts[0]["text"]


def test_no_space_alert_below_the_limit(api, monkeypatch):
    _disk(monkeypatch, 50)
    assert "espaco" not in _ids(api)


# --- daily backup -------------------------------------------------------------------------

def test_overdue_daily_backup_alert(api):
    c = _conn(api)
    set_setting(c, "last_daily_backup_at", iso_in(-3))
    c.close()
    a = next(a for a in api.get("/api/stats").json()["alerts"] if a["id"] == "backup_atrasado")
    assert a["href"].startswith("/#/ajuda/")


# --- notifications ------------------------------------------------------------------------

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
    set_setting(c, "notice_entrada_at", iso_in(-4))
    w._notices(c, "2026-11-02")
    assert sent.count("entrada") == 2
    c.close()


def test_critical_space_is_notified_daily(api, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "notify", lambda cfg, topic, *a: sent.append(topic))
    _disk(monkeypatch, 97, free_gb=1)
    c = _conn(api)
    w = _worker(api)
    w._notices(c, "2026-11-01")
    w._notices(c, "2026-11-01")
    assert sent.count("espaco") == 1
    set_setting(c, "notice_espaco_at", iso_in(-1.1))
    w._notices(c, "2026-11-02")
    assert sent.count("espaco") == 2
    c.close()


def test_card_topic_becomes_batch_topic(tmp_path):
    from acervo.db import load_migrations, migrate
    c = db.connect(tmp_path / "c.db")
    migrate(c, [m for m in load_migrations() if m.version <= 4])
    c.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, topics) "
              "VALUES ('https://x', 'k', 'a', '[\"espaco\"]')")
    migrate(c)
    rows = [json.loads(r[0]) for r in c.execute("SELECT topics FROM push_subscriptions ORDER BY id")]
    assert rows == [["espaco", "entrada", "lote"]]
    assert "lote" in push.TOPICS and "cartao" not in push.TOPICS


# --- the retired card ---------------------------------------------------------------------

def test_stranded_card_items_raise_an_alert_only_when_the_card_is_missing(sd_api, tmp_path, monkeypatch):
    iid = sd_api.upload(make_jpeg(tmp_path / "IMG_C.JPG"))["item_id"]
    sd_api.act([iid], "keep")
    put_on_card(sd_api.cfg, iid)
    s = sd_api.get("/api/stats").json()["storage"]
    assert s["card"]["present"] and s["card"]["library_bytes"] > 0
    assert "cartao" not in _ids(sd_api)
    card = sd_api.cfg.sd_dir
    card.rename(card.with_name("sd-fora"))
    try:
        assert "cartao" in _ids(sd_api)
        # The card being away is not a server failure.
        assert sd_api.client.get("/api/health").json()["problems"] == []
    finally:
        card.with_name("sd-fora").rename(card)


def test_no_card_section_without_a_card(api):
    assert api.get("/api/stats").json()["storage"]["card"] is None
