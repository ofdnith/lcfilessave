"""The microSD card: health checks and the offline browser that lives on it.

Health: cards fail silently (wear, a bad contact, fakes that lie about their
size). Every day a slice of the card is re-read and compared with the catalog's
SHA-256, oldest-checked first, so the whole card is covered every
SD_CHECK_CYCLE_DAYS. A damaged copy gets check_ok = 0: it stops counting as
"stored safely", so the iPhone's daily backup sends it again and the upload
repairs it (ingest._repair) — the iPhone backup never deletes anything.

Offline browser: like every HD (rule 8), the card carries ABRIR-ACERVO.html and
.acervo/miniaturas/, so someone who puts the card in any computer can browse
what is on it without installing anything.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import sqlite3

from .catalog import get_setting, iso_in, log_event, now_iso, set_setting, thumb_path
from .config import Config
from .storage import sha256_file
from .volume_export import render_open_html

log = logging.getLogger(__name__)

SD_CHECK_CYCLE_DAYS = 30
SD_CHECK_MIN_FILES = 20
SD_HTML = "ABRIR-ACERVO.html"
SD_THUMBS = ".acervo/miniaturas"
BROWSER_MIN_INTERVAL_DAYS = 1 / 48  # rewrite at most every 30 minutes while items keep arriving


def _present(cfg: Config) -> bool:
    return cfg.sd_dir is not None and cfg.sd_dir.is_dir()


# --- health ---------------------------------------------------------------------------------

def check_files(cfg: Config, conn: sqlite3.Connection, limit: int | None = None) -> dict:
    """Re-read today's slice of the card. Returns {'checked': n, 'damaged': [item ids]}."""
    report: dict = {"checked": 0, "damaged": []}
    if not _present(cfg):
        return report
    total = conn.execute("SELECT count(*) FROM files WHERE root = 'sd' AND rel_path IS NOT NULL").fetchone()[0]
    n = limit if limit is not None else max(SD_CHECK_MIN_FILES, math.ceil(total / SD_CHECK_CYCLE_DAYS))
    rows = conn.execute(
        "SELECT f.id, f.item_id, f.sha256, f.rel_path FROM files f WHERE f.root = 'sd' AND f.rel_path IS NOT NULL "
        "ORDER BY f.checked_at IS NOT NULL, f.checked_at, f.id LIMIT ?", (n,)).fetchall()
    for r in rows:
        path = cfg.sd_dir / r["rel_path"]
        try:
            ok = sha256_file(path) == r["sha256"]
        except OSError:
            if not _present(cfg):  # card removed mid-check: that says nothing about the files
                log.warning("Cartão microSD sumiu durante a verificação; continuo amanhã")
                break
            ok = False
        # Only the copy we read: if the file moved meanwhile, its row changed and this is a no-op.
        cur = conn.execute("UPDATE files SET checked_at = ?, check_ok = ? WHERE id = ? AND root = 'sd' AND rel_path = ?",
                           (now_iso(), int(ok), r["id"], r["rel_path"]))
        report["checked"] += 1
        if not ok and cur.rowcount:
            log_event(conn, "server", "sd-check-failed", item_id=r["item_id"], file_id=r["id"], sha256=r["sha256"],
                      from_path=f"sd:{r['rel_path']}")
            report["damaged"].append(r["item_id"])
    if report["damaged"]:
        log.warning("Cartão microSD: %d arquivos com defeito", len(report["damaged"]))
    return report


def health(cfg: Config, conn: sqlite3.Connection) -> dict:
    """Summary for /api/stats: damaged files and how much of the card was checked recently."""
    total, recent, damaged = conn.execute(
        "SELECT count(*), coalesce(sum(checked_at >= ?), 0), coalesce(sum(check_ok = 0), 0) "
        "FROM files WHERE root = 'sd' AND rel_path IS NOT NULL",
        (iso_in(-SD_CHECK_CYCLE_DAYS),)).fetchone()
    names = [r[0] for r in conn.execute(
        "SELECT i.original_name FROM files f JOIN items i ON i.id = f.item_id "
        "WHERE f.root = 'sd' AND f.rel_path IS NOT NULL AND f.check_ok = 0 ORDER BY i.captured_at LIMIT 5")]
    return {
        "damaged": damaged,
        "damaged_names": names,
        "checked_recent_pct": round(100 * recent / total, 1) if total else 100.0,
        "last_check_at": get_setting(conn, "sd_check_last_at"),
    }


# --- offline browser ------------------------------------------------------------------------

ITEMS_ON_CARD_SQL = """
    SELECT i.id, i.sha256, i.kind, i.original_name, coalesce(i.captured_at, i.uploaded_at) AS captured_at,
           i.size_bytes, i.place, i.important, i.thumb_status,
           (SELECT f.rel_path FROM files f WHERE f.item_id = i.id AND f.role = 'original') AS rel_path,
           (SELECT f.rel_path FROM files f WHERE f.item_id = i.id AND f.role = 'live-video'
              AND f.root = 'sd') AS live_rel_path
    FROM items i
    WHERE i.state = 'library' AND EXISTS (
        SELECT 1 FROM files f WHERE f.item_id = i.id AND f.role = 'original' AND f.root = 'sd' AND f.rel_path IS NOT NULL)
    ORDER BY captured_at DESC
"""


def signature(conn: sqlite3.Connection) -> str:
    """Changes whenever what is on the card changes (cheap; one indexed query)."""
    row = conn.execute(
        "SELECT count(*), coalesce(sum(f.id), 0), coalesce(sum(length(f.rel_path)), 0), "
        "coalesce(sum(i.thumb_status = 'ok'), 0), coalesce(sum(i.important), 0) "
        "FROM files f JOIN items i ON i.id = f.item_id "
        "WHERE f.root = 'sd' AND f.rel_path IS NOT NULL AND i.state = 'library'").fetchone()
    return ":".join(str(v) for v in row)


def write_browser(cfg: Config, conn: sqlite3.Connection) -> int:
    """(Re)write ABRIR-ACERVO.html and the thumbnails on the card. Returns item count."""
    if not _present(cfg):
        return 0
    rows = conn.execute(ITEMS_ON_CARD_SQL).fetchall()
    folder = cfg.sd_dir / SD_THUMBS
    folder.mkdir(parents=True, exist_ok=True)
    wanted: set[str] = set()
    for r in rows:
        if r["thumb_status"] != "ok":
            continue
        src = thumb_path(cfg, r["sha256"])
        name = f"{r['sha256']}.webp"
        dest = folder / name
        if src.is_file():
            wanted.add(name)
            if not dest.exists():
                tmp = dest.with_name(name + ".tmp")
                shutil.copyfile(src, tmp)
                os.replace(tmp, dest)
    for old in folder.iterdir():  # thumbnails of items that left the card (sent to an HD)
        if old.name not in wanted:
            old.unlink(missing_ok=True)

    items = [[r["kind"], r["original_name"], r["captured_at"], r["rel_path"], r["live_rel_path"],
              r["sha256"] if r["sha256"] + ".webp" in wanted else None, r["size_bytes"], r["place"], r["important"]]
             for r in rows]
    others = [[r["kind"], r["original_name"], r["captured_at"], r["vname"]] for r in conn.execute(
        "SELECT i.kind, i.original_name, coalesce(i.captured_at, i.uploaded_at) AS captured_at, v.name AS vname "
        "FROM items i JOIN volumes v ON v.id = i.volume_id WHERE i.state = 'archived' ORDER BY captured_at DESC")]
    html = render_open_html("Cartão microSD", items, others)
    target = cfg.sd_dir / SD_HTML
    tmp = target.with_name(SD_HTML + ".tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, target)
    return len(items)


# --- daily routine (called from the worker's maintenance) ---------------------------------

def maintain(cfg: Config, conn: sqlite3.Connection, today: str, notify=None) -> None:
    """Daily health slice + offline browser refreshed whenever the card changed."""
    if not (cfg.sd_for_library and _present(cfg)):
        return
    if get_setting(conn, "sd_check_last_date") != today:
        report = check_files(cfg, conn)
        set_setting(conn, "sd_check_last_date", today)
        set_setting(conn, "sd_check_last_at", now_iso())
        if report["damaged"] and notify:
            n = len(report["damaged"])
            notify("cartao", "Problema no cartão microSD",
                   f"{n} arquivo{'s' if n > 1 else ''} do cartão não conferem. Se ainda estiverem no iPhone, "
                   "o próximo backup diário os recupera. Considere trocar o cartão.", "/")
    sig = f"{today}:{signature(conn)}"  # at least daily: the list of what is on the HDs changes too
    last = get_setting(conn, "sd_browser_at")
    if sig != get_setting(conn, "sd_browser_sig") and (not last or last < iso_in(-BROWSER_MIN_INTERVAL_DAYS)):
        try:
            count = write_browser(cfg, conn)
        except OSError as exc:
            log.warning("Não consegui atualizar o ABRIR-ACERVO.html do cartão: %s", exc)
            return
        set_setting(conn, "sd_browser_sig", sig)
        set_setting(conn, "sd_browser_at", now_iso())
        log.info("ABRIR-ACERVO.html do cartão atualizado (%d itens)", count)
