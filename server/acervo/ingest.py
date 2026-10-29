"""From a fully received file to a cataloged item in the Entrada.

    received file ─► SHA-256 ─► already known? ─yes─► drop the new copy (identical bytes
                         │                              already stored), count it, report
                         no
                         ▼
                    metadata (date, GPS, Live Photo id…) ─► Live Photo video of a known
                         │                                   photo? attach to that item
                         ▼
                    item + file rows and the move into entrada/, in ONE transaction

"Already known" only counts when the known bytes are really safe (server copy
on disk, or a healthy verified copy on a drive, or deliberately discarded).
If the catalog knows the hash but the server copy vanished, the new upload
REPAIRS it instead of being thrown away.

Concurrency: a per-hash lock serialises two clients sending the same bytes at
the same time (the second one gets "já existe"); the UNIQUE(sha256)
constraints are the final arbiter. Names are chosen inside the write
transaction, so two different files with the same name never collide.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import db, media
from .catalog import (
    free_rel_path,
    library_dir,
    local_now,
    log_event,
    ms_to_local,
    now_iso,
    standard_name,
    transaction,
)
from .config import INBOX_DIR, LIBRARY_DIR, TRASH_DIR, Config
from .storage import move_verified, sha256_file

log = logging.getLogger(__name__)

STATUS_MESSAGES = {
    "new": "Recebido",
    "attached": "Vídeo da Live Photo juntado à foto",
    "duplicate": "Já estava no acervo",
    "in_trash": "Está na lixeira — quer restaurar?",
    "discarded": "Você já tinha descartado este arquivo",
    "restored": "Recuperado: a cópia guardada tinha sumido ou estava com problema",
    "failed": "Falhou",
}

# A drive copy counts only if it was verified, never failed a later health
# check, and its drive is not flagged with problems.
HEALTHY_DRIVE_COPY = """
    SELECT 1 FROM volume_copies vc JOIN volumes v ON v.id = vc.volume_id
    WHERE vc.file_id = ? AND vc.verified_at IS NOT NULL
      AND coalesce(vc.last_check_ok, 1) = 1 AND v.status <> 'problem'
"""


def server_copy_ok(cfg: Config, root: str, rel_path: str | None) -> bool:
    if rel_path is None:
        return False
    try:
        return (cfg.root_dir(root) / rel_path).is_file()
    except ValueError:  # microSD root no longer configured
        return False


def stored_safely(cfg: Config, conn: sqlite3.Connection, f: sqlite3.Row) -> bool:
    """Are these bytes really kept somewhere? (f: files row joined with items.state)"""
    if server_copy_ok(cfg, f["root"], f["rel_path"]):
        return True
    if f["state"] == "purged":
        return True  # the owner discarded it on purpose; nothing to keep
    return conn.execute(HEALTHY_DRIVE_COPY, (f["file_id"],)).fetchone() is not None


def valid_session(conn: sqlite3.Connection, session_id: int | None) -> int | None:
    """A stale session id (e.g. saved in a Shortcut) must not break uploads."""
    if session_id is None:
        return None
    return session_id if conn.execute("SELECT 1 FROM upload_sessions WHERE id = ?", (session_id,)).fetchone() else None


KNOWN_SQL = """
    SELECT f.id AS file_id, f.role, f.rel_path, f.root, i.id AS item_id, i.state, i.kind,
           i.captured_at, v.name AS volume_name
    FROM files f JOIN items i ON i.id = f.item_id LEFT JOIN volumes v ON v.id = i.volume_id
    WHERE f.sha256 = ?
"""


def normalize_client_time(value: object) -> int | None:
    """ms since epoch from ms (int/str) or ISO-8601 (naive = server local time)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().lstrip("-").isdigit()):
        ms = int(float(value))
        return ms if ms > 0 else None
    if isinstance(value, str):
        value = value.strip()
        lost_plus = re.fullmatch(r"(.+T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?) (\d{2}:?\d{2})", value)
        if lost_plus:  # '+03:00' arrives as ' 03:00' when not URL-encoded
            value = f"{lost_plus.group(1)}+{lost_plus.group(2)}"
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return int(dt.timestamp() * 1000)
    return None


def fingerprint_time(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms // 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def count_in_session(conn: sqlite3.Connection, session_id: int | None, sha: str, outcome: str, size: int,
                     client_key: str | None = None) -> None:
    """Count a confirmed client file once per session, however many times it is retried."""
    if session_id is None:
        return
    cur = conn.execute(
        "INSERT OR IGNORE INTO session_files (session_id, client_key, sha256, outcome) "
        "SELECT ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM upload_sessions WHERE id = ?)",
        (session_id, client_key or sha, sha, outcome, session_id),
    )
    if cur.rowcount != 1:
        return
    column = {"new": "new_count", "attached": "new_count", "existing": "existing_count"}[outcome]
    conn.execute(
        f"UPDATE upload_sessions SET received_verified_count = received_verified_count + 1, "
        f"{column} = {column} + 1, bytes_received = bytes_received + ? WHERE id = ?",
        (size, session_id),
    )


def count_failure(conn: sqlite3.Connection, session_id: int | None) -> None:
    if session_id is not None:
        conn.execute("UPDATE upload_sessions SET failed_count = failed_count + 1 WHERE id = ?", (session_id,))


def add_suggestion(conn: sqlite3.Connection, kind: str, group_key: str, item_ids: list[int]) -> None:
    row = conn.execute(
        "SELECT id FROM suggestions WHERE kind = ? AND group_key = ? AND status = 'open'", (kind, group_key)
    ).fetchone()
    sid = row[0] if row else conn.execute(
        "INSERT INTO suggestions (kind, group_key) VALUES (?, ?)", (kind, group_key)
    ).lastrowid
    conn.executemany(
        "INSERT OR IGNORE INTO suggestion_items (suggestion_id, item_id) VALUES (?, ?)",
        [(sid, i) for i in item_ids],
    )


def enqueue(conn: sqlite3.Connection, kind: str, item_id: int, priority: int, only_when_charging: bool = False) -> None:
    conn.execute(
        "INSERT INTO jobs (kind, item_id, priority, only_when_charging) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(kind, item_id) DO UPDATE SET status = 'pending', attempts = 0, last_error = NULL, "
        "run_after = excluded.run_after WHERE jobs.status IN ('failed', 'done')",
        (kind, item_id, priority, int(only_when_charging)),
    )


class Ingestor:
    def __init__(self, cfg: Config, exiftool: media.ExifTool | None) -> None:
        self.cfg = cfg
        self.exiftool = exiftool
        self._locks: dict[str, list] = {}  # sha -> [lock, users]
        self._guard = threading.Lock()

    @contextmanager
    def _sha_lock(self, sha: str) -> Iterator[None]:
        with self._guard:
            entry = self._locks.setdefault(sha, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._guard:
                entry[1] -= 1
                if entry[1] == 0:
                    self._locks.pop(sha, None)

    def ingest(self, tmp: Path, *, filename: str, source: str, session_id: int | None = None,
               client_modified: object = None, client_sha: str | None = None,
               actor: str = "server", client_key: str | None = None) -> dict:
        size = tmp.stat().st_size
        sha = sha256_file(tmp)
        client_ms = normalize_client_time(client_modified)

        if client_sha and client_sha.lower() != sha:
            tmp.unlink(missing_ok=True)
            conn = db.connect(self.cfg.db_path)
            try:
                with transaction(conn):
                    count_failure(conn, valid_session(conn, session_id))
            finally:
                conn.close()
            return {"status": "failed", "item_id": None, "sha256": sha,
                    "message": "O arquivo chegou diferente do enviado (hash não confere). Envie de novo."}

        with self._sha_lock(sha):
            conn = db.connect(self.cfg.db_path)
            try:
                session_id = valid_session(conn, session_id)
                known = conn.execute(KNOWN_SQL, (sha,)).fetchone()
                if known:
                    return self._already_known(conn, tmp, known, sha, size, filename, client_ms, session_id,
                                               client_key, actor)
                return self._new(conn, tmp, sha, size, filename, source, session_id, client_ms, actor, client_key)
            finally:
                conn.close()

    # -- content already in the catalog ----------------------------------------------------

    def _already_known(self, conn, tmp, known, sha, size, filename, client_ms, session_id, client_key, actor) -> dict:
        damaged = server_copy_ok(self.cfg, known["root"], known["rel_path"]) and \
            sha256_file(self.cfg.root_dir(known["root"]) / known["rel_path"]) != sha
        if damaged or not stored_safely(self.cfg, conn, known):
            return self._repair(conn, tmp, known, sha, size, filename, client_ms, session_id, client_key, actor)
        with transaction(conn):
            conn.execute(
                "INSERT INTO dedupe_hits (session_id, item_id, layer, original_name) VALUES (?, ?, 3, ?)",
                (session_id, known["item_id"], filename),
            )
            self._fingerprint(conn, filename, client_ms, size, known["item_id"])
            count_in_session(conn, session_id, sha, "existing", size, client_key)
        # Identical bytes (same SHA-256) are safely stored already: the new copy is redundant.
        tmp.unlink(missing_ok=True)
        status = {"trash": "in_trash", "purged": "discarded"}.get(known["state"], "duplicate")
        message = STATUS_MESSAGES[status]
        if known["state"] == "archived" and known["volume_name"]:
            message = f"Já está no {known['volume_name']}"
        return {"status": status, "item_id": known["item_id"], "sha256": sha, "message": message}

    def _repair(self, conn, tmp, known, sha, size, filename, client_ms, session_id, client_key, actor) -> dict:
        """The catalog knows these bytes but no safe copy exists: keep the new upload."""
        with transaction(conn):
            if known["rel_path"] is not None:
                root, rel = known["root"], known["rel_path"]  # put it back where the catalog says
            else:  # archived, but every drive copy failed its health check: back to the Acervo
                root = "main"
                directory = library_dir(known["captured_at"], known["kind"])
                rel = free_rel_path(conn, self.cfg, root, directory, filename_on_drive(conn, known["file_id"], filename))
                conn.execute("UPDATE files SET rel_path = ?, root = ? WHERE id = ?", (rel, root, known["file_id"]))
                if known["state"] == "archived":
                    conn.execute("UPDATE items SET state = 'library' WHERE id = ?", (known["item_id"],))
            self._fingerprint(conn, filename, client_ms, size, known["item_id"])
            count_in_session(conn, session_id, sha, "existing", size, client_key)
            log_event(conn, actor, "repair-from-upload", item_id=known["item_id"], file_id=known["file_id"],
                      sha256=sha, to_path=f"{root}:{rel}")
            dest = self.cfg.root_dir(root) / rel
            if dest.exists():  # present but damaged: keep it aside, never delete it blindly
                quarantine = self.cfg.subdir("tmp") / "corrompidos" / f"{now_iso()[:19].replace(':', '')}-{dest.name}"
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                os.replace(dest, quarantine)
            move_verified(tmp, dest, sha)
        log.warning("Arquivo %s recuperado a partir de um novo envio", rel)
        return {"status": "restored", "item_id": known["item_id"], "sha256": sha,
                "message": STATUS_MESSAGES["restored"]}

    def _fingerprint(self, conn, filename, client_ms, size, item_id) -> None:
        stamp = fingerprint_time(client_ms)
        if stamp:
            conn.execute(
                "INSERT OR IGNORE INTO fingerprints (original_name, client_created_at, size_bytes, item_id) "
                "VALUES (?, ?, ?, ?)", (filename, stamp, size, item_id),
            )

    # -- new content -----------------------------------------------------------------------

    def _new(self, conn, tmp, sha, size, filename, source, session_id, client_ms, actor, client_key) -> dict:
        kind = media.kind_of(filename)
        mime = media.guess_mime(filename)
        md = media.read_metadata(tmp, kind, self.exiftool)
        if md.mime and md.mime != "application/octet-stream" and kind in ("photo", "video", "audio"):
            mime = md.mime

        if kind == "video" and md.live_photo_id:
            attached = self._attach_live_video(conn, tmp, sha, size, filename, md, session_id, client_ms, actor, client_key)
            if attached:
                return attached

        if kind in ("photo", "video") and md.captured_at:
            captured_at, captured_tz, date_source = md.captured_at, md.captured_tz, md.date_source
        elif client_ms:
            (captured_at, captured_tz), date_source = ms_to_local(client_ms), "mtime"
        else:
            (captured_at, captured_tz), date_source = local_now(), "upload"

        std = standard_name(captured_at, filename)
        origin_app = media.detect_origin_app(filename)
        screenshot = kind == "photo" and media.looks_like_screenshot(filename, md)

        with transaction(conn):
            # Chosen inside the write transaction: a concurrent upload with the same
            # name waits here and then sees this file on disk.
            rel = free_rel_path(conn, self.cfg, "main", INBOX_DIR, std)
            item_id = conn.execute(
                """INSERT INTO items (sha256, kind, is_live_photo, live_photo_id, mime, size_bytes,
                       captured_at, captured_tz, date_source, source, upload_session_id, original_name,
                       standard_name, width, height, duration_ms, gps_lat, gps_lon, camera_make,
                       camera_model, is_screenshot, burst_id, origin_app, meta_status, thumb_status)
                   VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?)""",
                (sha, kind, md.live_photo_id if kind == "photo" else None, mime, size, captured_at,
                 captured_tz, date_source, source, session_id, filename, rel.rsplit("/", 1)[1],
                 md.width, md.height, md.duration_ms, md.gps_lat, md.gps_lon, md.camera_make,
                 md.camera_model, int(screenshot), md.burst_id, origin_app,
                 "pending" if kind in ("photo", "video") or mime == "application/pdf" else "none"),
            ).lastrowid
            file_id = conn.execute(
                "INSERT INTO files (item_id, role, sha256, size_bytes, mime, ext, rel_path, root) "
                "VALUES (?, 'original', ?, ?, ?, ?, ?, 'main')",
                (item_id, sha, size, mime, media.ext_of(filename), rel),
            ).lastrowid
            self._fingerprint(conn, filename, client_ms, size, item_id)
            count_in_session(conn, session_id, sha, "new", size, client_key)
            log_event(conn, actor, "ingest", item_id=item_id, file_id=file_id, sha256=sha, to_path=rel,
                      details={"source": source, "original_name": filename})

            if kind in ("photo", "video") or mime == "application/pdf":
                enqueue(conn, "thumbnail", item_id, priority=10)
            if md.gps_lat is not None:
                enqueue(conn, "place", item_id, priority=30)
            if kind == "document":
                enqueue(conn, "text", item_id, priority=40)
            if kind == "photo":
                enqueue(conn, "ocr", item_id, priority=90 if not screenshot else 50, only_when_charging=True)

            if screenshot:
                add_suggestion(conn, "screenshot", "", [item_id])
            if origin_app == "whatsapp":
                add_suggestion(conn, "whatsapp", "", [item_id])
            if kind == "video" and size >= media.LARGE_VIDEO_BYTES:
                add_suggestion(conn, "large-video", "", [item_id])
            if md.burst_id:
                others = [r[0] for r in conn.execute(
                    "SELECT id FROM items WHERE burst_id = ? AND id <> ? AND state = 'inbox'", (md.burst_id, item_id))]
                if others:
                    add_suggestion(conn, "burst", md.burst_id, [*others, item_id])

            # Last step inside the transaction: if the move fails, nothing is recorded.
            move_verified(tmp, self.cfg.data_dir / rel, sha)

        return {"status": "new", "item_id": item_id, "sha256": sha, "message": STATUS_MESSAGES["new"]}

    def _attach_live_video(self, conn, tmp, sha, size, filename, md, session_id, client_ms, actor, client_key) -> dict | None:
        # Only to a photo still on the server and not discarded: a video for a photo in
        # the trash becomes its own item in the Entrada instead (never purged on arrival).
        photo = conn.execute(
            """SELECT i.id, f.rel_path, f.root FROM items i
               JOIN files f ON f.item_id = i.id AND f.role = 'original'
               WHERE i.live_photo_id = ? AND i.kind = 'photo' AND f.rel_path IS NOT NULL
                 AND i.state IN ('inbox', 'library')
                 AND NOT EXISTS (SELECT 1 FROM files x WHERE x.item_id = i.id AND x.role = 'live-video')""",
            (md.live_photo_id,),
        ).fetchone()
        if not photo:
            return None
        directory, photo_name = photo["rel_path"].rsplit("/", 1)
        stem = photo_name.rsplit(".", 1)[0]
        ext = media.ext_of(filename) or "mov"
        original_ext = filename.rsplit(".", 1)[1] if "." in filename else "MOV"
        with transaction(conn):
            rel = free_rel_path(conn, self.cfg, photo["root"], directory, f"{stem}.{original_ext}")
            file_id = conn.execute(
                "INSERT INTO files (item_id, role, sha256, size_bytes, mime, ext, rel_path, root) "
                "VALUES (?, 'live-video', ?, ?, ?, ?, ?, ?)",
                (photo["id"], sha, size, media.guess_mime(filename), ext, rel, photo["root"]),
            ).lastrowid
            conn.execute(
                "UPDATE items SET is_live_photo = 1, size_bytes = size_bytes + ?, "
                "duration_ms = coalesce(duration_ms, ?) WHERE id = ?",
                (size, md.duration_ms, photo["id"]),
            )
            self._fingerprint(conn, filename, client_ms, size, photo["id"])
            count_in_session(conn, session_id, sha, "attached", size, client_key)
            log_event(conn, actor, "ingest-live-video", item_id=photo["id"], file_id=file_id, sha256=sha,
                      to_path=rel, details={"original_name": filename})
            move_verified(tmp, self.cfg.root_dir(photo["root"]) / rel, sha)
        return {"status": "attached", "item_id": photo["id"], "sha256": sha, "message": STATUS_MESSAGES["attached"]}


def filename_on_drive(conn: sqlite3.Connection, file_id: int, fallback: str) -> str:
    row = conn.execute("SELECT rel_path FROM volume_copies WHERE file_id = ? ORDER BY id LIMIT 1", (file_id,)).fetchone()
    return row[0].rsplit("/", 1)[-1] if row else fallback


# --- crash recovery ---------------------------------------------------------------------------

SKIP_SUFFIXES = (".tmp",)
PARTIAL_SUFFIX = ".part"
_STANDARD_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}_(.+)$")


def reconcile(cfg: Config, ingestor: Ingestor) -> dict:
    """Bring disk and catalog back in agreement after a crash. Idempotent.

    Must not run while another process changes the data dir: the server runs it
    at start-up before serving requests; `acervo verificar` refuses to run while
    the server holds the data-dir lock.

    For every file under entrada/, acervo/ and lixeira/ that the catalog does
    not point to (checked again, file by file, right before acting):
      * '.part' files are unfinished copies whose source still exists: removed;
      * same SHA-256 as a cataloged file whose recorded path is missing
        -> the move happened but the catalog update did not: fix the path;
      * same SHA-256 as a recorded copy that is intact (its hash is re-read)
        or as content safely on a drive / purged -> redundant copy: removed;
      * same SHA-256 as a recorded copy that turned out CORRUPTED -> the
        damaged one goes to tmp/corrompidos/ and this one takes its place;
      * unknown content -> ingested into the Entrada (never lose bytes).
    Files left in tmp/ by an interrupted reconcile are ingested too.
    """
    report = {"fixed_paths": 0, "removed_copies": 0, "reingested": 0, "repaired": 0,
              "partials_removed": 0, "missing": 0}
    conn = db.connect(cfg.db_path)
    try:
        for leftover in sorted(cfg.subdir("tmp").glob("reconcile-*")):
            if leftover.is_file():
                ingestor.ingest(leftover, filename=leftover.name.split("-", 2)[-1], source="web", actor="reconcile")
                report["reingested"] += 1
        roots = [("main", cfg.data_dir)] + ([("sd", cfg.sd_dir)] if cfg.sd_dir and cfg.sd_dir.is_dir() else [])
        for root, base in roots:
            for top in (INBOX_DIR, LIBRARY_DIR, TRASH_DIR):
                folder = base / top
                if not folder.is_dir():
                    continue
                for dirpath, _dirs, names in os.walk(folder):
                    for name in names:
                        path = Path(dirpath) / name
                        if name.endswith(PARTIAL_SUFFIX):
                            path.unlink(missing_ok=True)
                            report["partials_removed"] += 1
                            continue
                        if name.endswith(SKIP_SUFFIXES) or name.startswith("."):
                            continue
                        _reconcile_one(cfg, conn, ingestor, root, path.relative_to(base).as_posix(), path, report)
        for r in conn.execute("SELECT root, rel_path FROM files WHERE rel_path IS NOT NULL"):
            base = cfg.data_dir if r[0] == "main" else cfg.sd_dir
            if base is not None and not (base / r[1]).exists():
                report["missing"] += 1
    finally:
        conn.close()
    if any(v for k, v in report.items() if k != "missing"):
        log.warning("Reconciliação: %s", report)
    return report


def _reconcile_one(cfg, conn, ingestor, root, rel, path, report) -> None:
    # The catalog may have changed since the walk started: look again, now.
    if conn.execute("SELECT 1 FROM files WHERE root = ? AND rel_path = ?", (root, rel)).fetchone():
        return
    if not path.is_file():
        return
    sha = sha256_file(path)
    row = conn.execute(KNOWN_SQL, (sha,)).fetchone()
    if row is None:
        tmp = cfg.subdir("tmp") / f"reconcile-{sha[:16]}-{path.name}"
        move_verified(path, tmp, sha)
        m = _STANDARD_NAME.match(path.name)
        ingestor.ingest(tmp, filename=m.group(1) if m else path.name, source="web", actor="reconcile")
        report["reingested"] += 1
        return

    if row["rel_path"] is not None:
        recorded = cfg.root_dir(row["root"]) / row["rel_path"]
        if not recorded.is_file():
            with transaction(conn):
                conn.execute("UPDATE files SET rel_path = ?, root = ? WHERE id = ?", (rel, root, row["file_id"]))
                log_event(conn, "reconcile", "fix-path", item_id=row["item_id"], file_id=row["file_id"], sha256=sha,
                          from_path=row["rel_path"], to_path=rel)
            report["fixed_paths"] += 1
            return
        if sha256_file(recorded) == sha:
            with transaction(conn):  # verified identical to the intact recorded copy
                log_event(conn, "reconcile", "remove-redundant-copy", item_id=row["item_id"],
                          file_id=row["file_id"], sha256=sha, from_path=rel)
            path.unlink()
            report["removed_copies"] += 1
            return
        # The recorded copy is damaged; this one is the good one.
        quarantine = cfg.subdir("tmp") / "corrompidos" / f"{now_iso()[:19].replace(':', '')}-{recorded.name}"
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        with transaction(conn):
            log_event(conn, "reconcile", "repair-corrupted-copy", item_id=row["item_id"], file_id=row["file_id"],
                      sha256=sha, from_path=rel, to_path=row["rel_path"],
                      details={"quarantine": str(quarantine)})
            os.replace(recorded, quarantine)
            move_verified(path, recorded, sha)
        report["repaired"] += 1
        return

    if stored_safely(cfg, conn, row):
        with transaction(conn):  # identical to content safely on a drive, or purged on purpose
            log_event(conn, "reconcile", "remove-redundant-copy", item_id=row["item_id"], file_id=row["file_id"],
                      sha256=sha, from_path=rel)
        path.unlink()
        report["removed_copies"] += 1
        return
    # The catalog says the bytes left the server, but no healthy copy exists: keep this one.
    with transaction(conn):
        conn.execute("UPDATE files SET rel_path = ?, root = ? WHERE id = ?", (rel, root, row["file_id"]))
        if row["state"] == "archived":
            conn.execute("UPDATE items SET state = 'library' WHERE id = ?", (row["item_id"],))
        log_event(conn, "reconcile", "fix-path", item_id=row["item_id"], file_id=row["file_id"], sha256=sha, to_path=rel)
    report["fixed_paths"] += 1


__all__ = ["Ingestor", "reconcile", "normalize_client_time", "fingerprint_time", "stored_safely", "now_iso"]
