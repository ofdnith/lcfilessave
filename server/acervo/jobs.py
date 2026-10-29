"""Background work, persisted in the `jobs` table.

One worker thread, lowest CPU priority. If Android kills the process, jobs
marked 'running' go back to 'pending' on the next start — nothing is lost.

Jobs:
  thumbnail  WebP thumbnail (+ perceptual hash and near-duplicate grouping for photos)
  place      GPS -> city name (offline)
  text       text of documents for search
  ocr        text in photos (only while charging), read from a reduced copy
While the battery is too hot (max_temp_c) the worker pauses until it cools.
Maintenance (every 10 minutes): purge expired trash once a day, daily catalog
backup, WAL checkpoint, cleanup of abandoned uploads and of the preview cache.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import date

from . import db, media, power
from .catalog import get_setting, iso_in, medium_path, now_iso, preview_path, set_setting, thumb_path, transaction
from .config import Config
from .ingest import add_suggestion
from .library import migrate_to_sd, purge_expired, resolve_suggestions, sd_available
from .neardup import PhashIndex
from .places import Gazetteer
from .textextract import extract_text, ocr_image

log = logging.getLogger(__name__)

NEAR_DUP_DISTANCE = 10
MAX_ATTEMPTS = 5
PREVIEW_CACHE_BYTES = 2_000_000_000
SD_RESCUE_DIR = "acervo-resgate"
SD_README = """ACERVO — cartão microSD

Este cartão guarda tudo o que já passou pela triagem e ainda não foi para um HD.
Se o celular se perder, os arquivos continuam aqui:

  acervo/AAAA/MM/fotos, videos, docs, audios, outros   os originais, intactos
  acervo-resgate/catalogo-AAAA-MM-DD.db                 cópia diária do catálogo

Para ler num computador: tire o cartão, use um leitor e abra a pasta
Android/data/com.termux/files/acervo. Os arquivos são comuns (JPEG, HEIC, MOV…).

Para voltar a ter o Acervo completo num celular novo: instale o Acervo,
copie o catálogo mais recente para ~/acervo-dados/catalogo.db, aponte sd_dir
para esta pasta e rode `acervo-ctl verificar` (o que estava só na Entrada
vai aparecer como não encontrado).

O que já foi para HD está nos HDs; o que ainda estava na Entrada (sem triagem)
estava só no celular.
"""


class RetryLater(Exception):
    """Not an error: the job cannot run yet (e.g. city database not downloaded)."""


class Worker:
    def __init__(self, cfg: Config, exiftool: media.ExifTool | None, gazetteer: Gazetteer) -> None:
        self.cfg = cfg
        self.exiftool = exiftool
        self.gazetteer = gazetteer
        self.thermal = power.ThermalGate(cfg.max_temp_c)
        self.phashes = PhashIndex()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads: list[threading.Thread] = []

    # -- lifecycle ----------------------------------------------------------------------

    def recover(self) -> None:
        conn = db.connect(self.cfg.db_path)
        try:
            conn.execute("UPDATE jobs SET status = 'pending', updated_at = ? WHERE status = 'running'", (now_iso(),))
        finally:
            conn.close()

    def start(self) -> None:
        self.recover()
        loops = [(self._loop, "acervo-jobs"), (self._maintenance_loop, "acervo-maintenance")]
        if self.cfg.sd_for_library:
            loops.append((self._sd_loop, "acervo-sd"))
        for target, name in loops:
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for t in self._threads:
            t.join(timeout=10)

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        try:  # Linux/Android: lower the priority of this thread only
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 15)
        except (AttributeError, OSError):
            pass
        while not self._stop.is_set():
            if self.thermal.too_hot():
                self._stop.wait(timeout=60)
                continue
            try:
                did = self.run_once()
            except Exception:
                log.exception("Erro no trabalhador")
                did = False
            if not did:
                self._wake.wait(timeout=5)
                self._wake.clear()

    def _sd_loop(self) -> None:
        """Keeps the microSD in step with the Acervo: whatever was kept in triage
        is copied there (verified) within minutes. Idle checks once a minute."""
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        except (AttributeError, OSError):
            pass
        while not self._stop.is_set():
            moved = 0
            try:
                moved = migrate_to_sd(self.cfg)
            except Exception:
                log.exception("Erro ao copiar para o cartão microSD")
            if not moved:
                self._stop.wait(timeout=60)

    def _maintenance_loop(self) -> None:
        delay = 30  # first run shortly after start, then every 10 minutes
        while not self._stop.wait(timeout=delay):
            delay = 600
            try:
                self.maintenance()
            except Exception:
                log.exception("Erro na manutenção")

    # -- jobs ---------------------------------------------------------------------------

    def run_pending(self, max_jobs: int = 10_000) -> int:
        """Run jobs until none is ready (used by tests and `acervo processar`)."""
        n = 0
        while n < max_jobs and self.run_once():
            n += 1
        return n

    def run_once(self) -> bool:
        conn = db.connect(self.cfg.db_path)
        try:
            if get_setting(conn, "migration_active"):
                return False  # frozen while the files are copied to the new server
            now = now_iso()
            job = conn.execute(
                """UPDATE jobs SET status = 'running', started_at = ?, updated_at = ?, attempts = attempts + 1
                   WHERE id = (SELECT id FROM jobs WHERE status = 'pending' AND run_after <= ?
                               AND (only_when_charging = 0 OR ? = 1)
                               ORDER BY priority, id LIMIT 1)
                   RETURNING id, kind, item_id, attempts""",
                (now, now, now, int(power.is_charging())),
            ).fetchone()
            if job is None:
                return False
            try:
                getattr(self, f"_job_{job['kind']}")(conn, job["item_id"])
            except RetryLater as wait:
                conn.execute(
                    "UPDATE jobs SET status = 'pending', attempts = attempts - 1, run_after = ?, last_error = ? "
                    "WHERE id = ?", (iso_in(1), str(wait), job["id"]))
            except Exception as exc:
                final = job["attempts"] >= MAX_ATTEMPTS or isinstance(exc, media.CannotRender)
                log.info("Tarefa %s do item %s falhou: %s", job["kind"], job["item_id"], exc)
                conn.execute(
                    "UPDATE jobs SET status = ?, last_error = ?, run_after = ?, updated_at = ? WHERE id = ?",
                    ("failed" if final else "pending", str(exc)[:500],
                     iso_in(2 ** job["attempts"] / 1440), now_iso(), job["id"]))
                if final and job["kind"] == "thumbnail":
                    conn.execute("UPDATE items SET thumb_status = 'failed', medium_status = CASE medium_status "
                                 "WHEN 'pending' THEN 'failed' ELSE medium_status END WHERE id = ?", (job["item_id"],))
            else:
                conn.execute("UPDATE jobs SET status = 'done', last_error = NULL, updated_at = ? WHERE id = ?",
                             (now_iso(), job["id"]))
            return True
        finally:
            conn.close()

    def _source(self, conn: sqlite3.Connection, item_id: int):
        row = conn.execute(
            "SELECT i.*, f.rel_path, f.root, f.ext FROM items i "
            "JOIN files f ON f.item_id = i.id AND f.role = 'original' WHERE i.id = ?", (item_id,)
        ).fetchone()
        if row is None or row["rel_path"] is None or row["state"] == "purged":
            return row, None
        return row, self.cfg.root_dir(row["root"]) / row["rel_path"]

    def _job_thumbnail(self, conn: sqlite3.Connection, item_id: int) -> None:
        item, path = self._source(conn, item_id)
        if path is None:
            return
        im = media.render_source(path, item["kind"], item["ext"], self.exiftool)
        media.write_thumbnail(im, thumb_path(self.cfg, item["sha256"]))
        medium = "none"
        if item["kind"] in ("photo", "video"):
            media.write_medium(im, medium_path(self.cfg, item["sha256"]))
            medium = "ok"
        phash = media.phash(im) if item["kind"] == "photo" else None
        with transaction(conn):
            conn.execute(
                "UPDATE items SET thumb_status = 'ok', medium_status = ?, phash = coalesce(phash, ?), "
                "width = coalesce(width, ?), height = coalesce(height, ?) WHERE id = ?",
                (medium, phash, im.width, im.height, item_id))
            if phash is not None and item["state"] == "inbox":
                self._group_near_duplicates(conn, item, phash)
        if phash is not None:
            self.phashes.add(item_id, phash)

    def _group_near_duplicates(self, conn: sqlite3.Connection, item: sqlite3.Row, phash: int) -> None:
        if not self.phashes.loaded:
            self.phashes.load(conn)
        candidates = self.phashes.near(phash, NEAR_DUP_DISTANCE, exclude=item["id"])
        if not candidates:
            return
        # The index may hold items that were discarded since; the catalog decides.
        near = [r[0] for r in conn.execute(
            f"SELECT id FROM items WHERE id IN ({','.join('?' * len(candidates))}) "
            "AND state IN ('inbox', 'library', 'archived') ORDER BY id", candidates)]
        if not near:
            return
        marks = ",".join("?" * len(near))
        existing = conn.execute(
            f"SELECT s.group_key FROM suggestions s JOIN suggestion_items si ON si.suggestion_id = s.id "
            f"WHERE s.kind = 'near-duplicate' AND s.status = 'open' AND si.item_id IN ({marks}) LIMIT 1",
            near).fetchone()
        add_suggestion(conn, "near-duplicate", existing[0] if existing else f"nd:{item['id']}", [*near, item["id"]])
        if item["upload_session_id"]:
            conn.execute("UPDATE upload_sessions SET near_dup_count = near_dup_count + 1 WHERE id = ?",
                         (item["upload_session_id"],))

    def _job_place(self, conn: sqlite3.Connection, item_id: int) -> None:
        row = conn.execute("SELECT gps_lat, gps_lon FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None or row["gps_lat"] is None:
            return
        if not self.gazetteer.available:
            raise RetryLater("base de cidades não baixada (acervo baixar-cidades)")
        place = self.gazetteer.lookup(row["gps_lat"], row["gps_lon"])
        if place:
            conn.execute("UPDATE items SET place = ? WHERE id = ?", (place, item_id))

    def _job_text(self, conn: sqlite3.Connection, item_id: int) -> None:
        item, path = self._source(conn, item_id)
        if path is None:
            return
        text = extract_text(path, item["ext"])
        if text:
            conn.execute("UPDATE search_fts SET body = ? WHERE rowid = ?", (text, item_id))

    def _job_ocr(self, conn: sqlite3.Connection, item_id: int) -> None:
        item, path = self._source(conn, item_id)
        if path is None:
            return
        # Never the full-resolution original: a 12-48 MP photo takes tesseract
        # tens of seconds on the phone. The 1600 px preview keeps text readable.
        im = media.render_source(path, "photo", item["ext"], self.exiftool)
        if item["mime"] in ("image/jpeg", "image/png") and max(im.size) <= media.PREVIEW_SIZE:
            text = ocr_image(path)  # already small (e.g. a screenshot): read it as is
        else:
            tmp = self.cfg.subdir("tmp") / f"ocr-{item_id}.png"
            try:
                media.write_ocr_image(im, tmp)
                text = ocr_image(tmp)
            finally:
                tmp.unlink(missing_ok=True)
        if text:
            conn.execute("UPDATE search_fts SET body = ? WHERE rowid = ?", (text, item_id))

    def _job_embedding(self, conn: sqlite3.Connection, item_id: int) -> None:  # phase 7, not enabled
        return

    # -- maintenance --------------------------------------------------------------------

    def maintenance(self) -> None:
        cfg = self.cfg
        conn = db.connect(cfg.db_path)
        try:
            if get_setting(conn, "migration_active"):
                return
            today = date.today().isoformat()
            if get_setting(conn, "last_purge_date") != today:
                purge_expired(cfg)
                set_setting(conn, "last_purge_date", today)
            resolve_suggestions(conn)
            self._backfill_medium(conn)
            self._expire_uploads(conn)
            conn.execute("DELETE FROM jobs WHERE status = 'done' AND updated_at < ?", (iso_in(-7),))
            self._notices(conn, today)
            if cfg.catalog_backup_dir is not None and get_setting(conn, "last_backup_date") != today:
                self._backup_catalog(conn, today, cfg.catalog_backup_dir)
                set_setting(conn, "last_backup_date", today)
            if cfg.sd_for_library and sd_available(cfg) and get_setting(conn, "last_sd_backup_date") != today:
                self._backup_to_sd(conn, today)
                set_setting(conn, "last_sd_backup_date", today)
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        finally:
            conn.close()
        self._trim_previews()

    def _notices(self, conn: sqlite3.Connection, today: str) -> None:
        """Push notifications for things the owner should know without opening the app."""
        from . import push
        from .storage import disk_usage
        last = get_setting(conn, "last_daily_backup_at")
        if last and last < iso_in(-2) and get_setting(conn, "notice_overdue_date") != today:
            set_setting(conn, "notice_overdue_date", today)
            push.notify(self.cfg, "backup_atrasado", "Backup diário atrasado",
                        "O iPhone não manda fotos há mais de 48 horas. Confira a automação do Atalhos.", "/#/ajustes")
        usage = disk_usage(self.cfg.data_dir)
        server_bytes = conn.execute("SELECT coalesce(sum(size_bytes), 0) FROM files WHERE rel_path IS NOT NULL").fetchone()[0]
        full = usage.used_pct >= self.cfg.storage_alert_pct or server_bytes >= self.cfg.archive_batch_gb * 1_000_000_000
        last_space = get_setting(conn, "notice_space_at")
        if full and (not last_space or last_space < iso_in(-3)):
            set_setting(conn, "notice_space_at", now_iso())
            push.notify(self.cfg, "espaco", "Servidor ficando cheio",
                        f"{server_bytes / 1e9:.0f} GB no servidor. Hora de transferir um lote para um HD.", "/")

    def _backfill_medium(self, conn: sqlite3.Connection) -> None:
        """Items from before medium previews existed: render them, 500 per round."""
        from .ingest import enqueue
        rows = conn.execute(
            "SELECT i.id FROM items i JOIN files f ON f.item_id = i.id AND f.role = 'original' "
            "WHERE i.medium_status = 'pending' AND i.kind IN ('photo', 'video') AND f.rel_path IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.item_id = i.id AND j.kind = 'thumbnail' "
            "AND j.status IN ('pending', 'running')) LIMIT 500").fetchall()
        for r in rows:
            enqueue(conn, "thumbnail", r[0], priority=60)
        # Archived before this version: the original is gone; the thumbnail is the best we have.
        conn.execute("UPDATE items SET medium_status = 'none' WHERE medium_status = 'pending' AND state = 'archived' "
                     "AND NOT EXISTS (SELECT 1 FROM files f WHERE f.item_id = items.id AND f.rel_path IS NOT NULL)")

    def _expire_uploads(self, conn: sqlite3.Connection) -> None:
        old = conn.execute(
            "SELECT id FROM uploads WHERE status IN ('receiving', 'cancelled') AND updated_at < ?", (iso_in(-7),)
        ).fetchall()
        for row in old:
            (self.cfg.subdir("tmp") / "uploads" / f"{row['id']}.part").unlink(missing_ok=True)
        conn.execute("DELETE FROM uploads WHERE status IN ('receiving', 'cancelled') AND updated_at < ?", (iso_in(-7),))
        conn.execute("DELETE FROM uploads WHERE status IN ('done', 'failed') AND updated_at < ?", (iso_in(-30),))

    def _backup_to_sd(self, conn: sqlite3.Connection, today: str) -> None:
        """If the phone is lost, the card alone must be enough: the originals are
        in acervo/AAAA/MM/…, and next to them a copy of the catalog (dates,
        places, which HD holds what) and a note on how to use it."""
        folder = self.cfg.sd_dir / SD_RESCUE_DIR
        try:
            self._backup_catalog(conn, today, folder, keep=3)
            (folder / "LEIA-ME.txt").write_text(SD_README, encoding="utf-8")
        except OSError as exc:
            log.warning("Não consegui salvar a cópia do catálogo no cartão: %s", exc)

    def _backup_catalog(self, conn: sqlite3.Connection, today: str, dest_dir, keep: int = 7) -> None:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"catalogo-{today}.db"
        target = sqlite3.connect(dest)
        try:
            conn.backup(target)
        finally:
            target.close()
        backups = sorted(dest_dir.glob("catalogo-*.db"))
        for old in backups[:-keep]:
            old.unlink(missing_ok=True)
        log.info("Cópia do catálogo salva em %s", dest)

    def _trim_previews(self) -> None:
        folder = self.cfg.subdir("previas")
        if not folder.is_dir():
            return
        files = [(p.stat().st_atime, p.stat().st_size, p) for p in folder.rglob("*.jpg")]
        total = sum(s for _, s, _ in files)
        for _, size, p in sorted(files):
            if total <= PREVIEW_CACHE_BYTES:
                break
            p.unlink(missing_ok=True)
            total -= size


def preview_for(cfg: Config, exiftool: media.ExifTool | None, item: sqlite3.Row, path) -> "os.PathLike":
    """Browser-viewable JPEG of a photo the browser cannot show (HEIC, TIFF, RAW…), cached."""
    dest = preview_path(cfg, item["sha256"])
    if not dest.exists():
        media.write_preview(media.render_source(path, "photo", item["ext"], exiftool), dest)
    return dest


__all__ = ["Worker", "preview_for"]
