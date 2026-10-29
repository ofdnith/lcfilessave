"""State changes that move bytes: keep, discard (to trash), restore, purge.

Pattern for every operation, so a killed process never loses a file:
  BEGIN; update catalog rows; log the event; move the file(s); COMMIT.
If the move fails the transaction rolls back. If the process dies after the
move but before COMMIT, ingest.reconcile() finds the file by its hash and
fixes the path on the next start.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from . import db
from .catalog import (free_rel_path, get_setting, inbox_bytes, iso_in, library_bytes_by_root, library_dir, log_event, now_iso,
                      preview_path, transaction)
from .config import INBOX_DIR, TRASH_DIR, Config
from .storage import VerificationError, copy_verified, disk_usage, fsync_dir, move_verified

log = logging.getLogger(__name__)


class ActionError(ValueError):
    """Message in Portuguese, shown to the user."""


SD_MARGIN_BYTES = 1_000_000_000
SD_BATCH_BYTES = 2_000_000_000  # per migrate_to_sd() call, so the loop stays responsive


def sd_available(cfg: Config) -> bool:
    return cfg.sd_dir is not None and cfg.sd_dir.is_dir()


def sd_has_room(cfg: Config, size: int) -> bool:
    return sd_available(cfg) and disk_usage(cfg.sd_dir).free_bytes > size * 2 + SD_MARGIN_BYTES


def choose_root(cfg: Config, size: int) -> str:
    """Where a kept item goes at triage time.

    sd_for_library: internal storage, instantly; migrate_to_sd() then copies it to
    the microSD in the background (copying in the request would make triage
    wait on the card). Otherwise: internal storage, and the card only once
    internal storage passes the alert level.
    """
    if cfg.sd_for_library or not sd_available(cfg):
        return "main"
    if disk_usage(cfg.data_dir).used_pct < cfg.storage_alert_pct:
        return "main"
    return "sd" if sd_has_room(cfg, size) else "main"


def _files(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, role, sha256, rel_path, root FROM files WHERE item_id = ? ORDER BY role = 'live-video'",
        (item_id,),
    ).fetchall()


def _move_files(cfg: Config, conn: sqlite3.Connection, item: sqlite3.Row, root: str, directory: str,
                action: str, actor: str) -> None:
    """Called inside a transaction. If any file fails to move (a Live Photo has two),
    the ones already moved are moved back before the transaction rolls back, so
    disk and catalog never disagree."""
    files = _files(conn, item["id"])
    if any(f["rel_path"] is None for f in files):
        raise ActionError("O original não está no servidor.")
    done: list[tuple] = []
    try:
        for f in files:
            name = f["rel_path"].rsplit("/", 1)[1]
            new_rel = free_rel_path(conn, cfg, root, directory, name)
            conn.execute("UPDATE files SET rel_path = ?, root = ? WHERE id = ?", (new_rel, root, f["id"]))
            log_event(conn, actor, action, item_id=item["id"], file_id=f["id"], sha256=f["sha256"],
                      from_path=f"{f['root']}:{f['rel_path']}", to_path=f"{root}:{new_rel}")
            src, dst = cfg.root_dir(f["root"]) / f["rel_path"], cfg.root_dir(root) / new_rel
            move_verified(src, dst, f["sha256"])
            done.append((src, dst, f["sha256"]))
    except BaseException:
        for src, dst, sha in reversed(done):
            try:
                move_verified(dst, src, sha)
            except OSError:
                log.exception("Não consegui desfazer a movimentação de %s; a verificação corrige no próximo início", dst)
        raise


def _item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ActionError("Item não encontrado.")
    return row


def keep(cfg: Config, conn: sqlite3.Connection, item_id: int, actor: str = "web") -> None:
    item = _item(conn, item_id)
    if item["state"] == "library":
        return
    if item["state"] != "inbox":
        raise ActionError("Só itens da Entrada podem ser mantidos.")
    root = choose_root(cfg, item["size_bytes"])
    with transaction(conn):
        conn.execute("UPDATE items SET state = 'library' WHERE id = ?", (item_id,))
        _move_files(cfg, conn, item, root, library_dir(item["captured_at"], item["kind"]), "keep", actor)


def discard(cfg: Config, conn: sqlite3.Connection, item_id: int, actor: str = "web") -> None:
    item = _item(conn, item_id)
    if item["state"] == "trash":
        return
    if item["state"] not in ("inbox", "library"):
        raise ActionError("Itens que estão no HD não podem ir para a lixeira.")
    root = _files(conn, item_id)[0]["root"]
    with transaction(conn):
        conn.execute(
            "UPDATE items SET state = 'trash', trashed_at = ?, state_before_trash = ? WHERE id = ?",
            (now_iso(), item["state"], item_id),
        )
        _move_files(cfg, conn, item, root, TRASH_DIR, "trash", actor)


def restore(cfg: Config, conn: sqlite3.Connection, item_id: int, actor: str = "web") -> None:
    item = _item(conn, item_id)
    if item["state"] != "trash":
        if item["state"] == "purged":
            raise ActionError("Este item já foi apagado de vez.")
        return
    target = item["state_before_trash"]
    root = "main" if target == "inbox" else _files(conn, item_id)[0]["root"]
    directory = INBOX_DIR if target == "inbox" else library_dir(item["captured_at"], item["kind"])
    with transaction(conn):
        conn.execute(
            "UPDATE items SET state = ?, trashed_at = NULL, state_before_trash = NULL WHERE id = ?",
            (target, item_id),
        )
        _move_files(cfg, conn, item, root, directory, "restore", actor)


class _Changed(Exception):
    """The item changed (discarded, moved) while its copy was being made."""


def _copy_then_switch(cfg: Config, conn: sqlite3.Connection, item_id: int, root: str, action: str,
                      actor: str) -> bool:
    """Move an item's files that are not yet on `root` there, across filesystems,
    without holding the catalog lock during the copy:

      1. copy each file, fsync, re-read the copy and compare SHA-256 (no lock);
      2. BEGIN; check nothing changed; point the catalog at the copies; COMMIT;
      3. only then remove the old files.

    Dying after 1: the copies are unrecorded and identical to the recorded
    originals, so reconcile() deletes them. Dying after 2: the old files are
    the redundant ones and reconcile() deletes those. Either way, one verified
    copy is always recorded (rule 3).
    """
    item = _item(conn, item_id)
    files = [f for f in _files(conn, item_id) if f["root"] != root]
    if not files:
        return False
    if any(f["rel_path"] is None for f in files):
        raise ActionError("O original não está no servidor.")
    directory = library_dir(item["captured_at"], item["kind"])
    made: list[tuple[sqlite3.Row, str, Path, Path]] = []
    try:
        for f in files:
            name = f["rel_path"].rsplit("/", 1)[1]
            new_rel = free_rel_path(conn, cfg, root, directory, name)
            src, dst = cfg.root_dir(f["root"]) / f["rel_path"], cfg.root_dir(root) / new_rel
            copy_verified(src, dst, f["sha256"])
            made.append((f, new_rel, src, dst))
        with transaction(conn):
            fresh = _item(conn, item_id)
            now = {r["id"]: r for r in _files(conn, item_id)}
            # A migration to a new server froze the catalog while we copied: its
            # file list has the old paths, so nothing may move now.
            if get_setting(conn, "migration_active") or fresh["state"] != item["state"] or any(
                    f["id"] not in now or now[f["id"]]["root"] != f["root"]
                    or now[f["id"]]["rel_path"] != f["rel_path"] for f, *_ in made):
                raise _Changed
            for f, new_rel, _src, _dst in made:
                conn.execute("UPDATE files SET rel_path = ?, root = ? WHERE id = ?", (new_rel, root, f["id"]))
                log_event(conn, actor, action, item_id=item_id, file_id=f["id"], sha256=f["sha256"],
                          from_path=f"{f['root']}:{f['rel_path']}", to_path=f"{root}:{new_rel}")
    except BaseException:
        for *_, dst in made:  # only copies this call created and verified
            dst.unlink(missing_ok=True)
        raise
    for _f, _rel, src, _dst in made:
        src.unlink(missing_ok=True)
        fsync_dir(src.parent)
    return True


def migrate_to_sd(cfg: Config, actor: str = "server", max_bytes: int = SD_BATCH_BYTES) -> int:
    """Copy kept items still on internal storage to the microSD (sd_for_library),
    verified by SHA-256, then free the internal copy. Returns how many moved.

    Called in a loop by the worker; `max_bytes` bounds one call so the loop
    stays responsive. Stops at the first card error (removed, full, failing).
    """
    if not cfg.sd_for_library or not sd_available(cfg):
        return 0
    conn = db.connect(cfg.db_path)
    moved = done_bytes = 0
    try:
        if get_setting(conn, "migration_active"):
            return 0
        rows = conn.execute(
            "SELECT i.id, sum(f.size_bytes) AS size FROM items i JOIN files f ON f.item_id = i.id "
            "WHERE i.state = 'library' AND f.root = 'main' AND f.rel_path IS NOT NULL "
            "GROUP BY i.id ORDER BY i.id").fetchall()
        for row in rows:
            if done_bytes and done_bytes + row["size"] > max_bytes:
                break
            if not sd_has_room(cfg, row["size"]):
                log.info("Cartão microSD cheio: itens do Acervo continuam na memória interna "
                         "até um lote ir para o HD")
                break
            try:
                if _copy_then_switch(cfg, conn, row["id"], "sd", "to-sd", actor):
                    moved += 1
                    done_bytes += row["size"]
            except _Changed:
                continue
            except (ActionError, OSError, VerificationError) as exc:
                log.warning("Não consegui copiar o item %s para o cartão: %s", row["id"], exc)
                break
    finally:
        conn.close()
    if moved:
        log.info("Cartão microSD: %d itens do Acervo copiados e conferidos", moved)
    return moved


def storage_summary(cfg: Config, conn: sqlite3.Connection) -> dict:
    """Entrada limit and microSD state, for /api/stats and /api/health."""
    inbox = inbox_bytes(conn)
    limit = cfg.inbox_max_gb * 1_000_000_000
    data: dict = {
        "inbox_bytes": inbox,
        "inbox_max_bytes": limit or None,
        "inbox_alert": bool(limit) and inbox >= limit * 0.9,
        "sd": None,
    }
    if cfg.sd_dir is not None:
        present = sd_available(cfg)
        usage = disk_usage(cfg.sd_dir) if present else None
        pending = pending_sd_bytes(conn) if cfg.sd_for_library else 0
        data["sd"] = {
            "present": present,
            "for_library": cfg.sd_for_library,
            "total_bytes": usage.total_bytes if usage else None,
            "free_bytes": usage.free_bytes if usage else None,
            "used_pct": usage.used_pct if usage else None,
            "library_bytes": library_bytes_by_root(conn)["sd"],
            "pending_bytes": pending,
            # Full enough that the next HD batch should come from the card.
            "alert": (not present) or (usage is not None and usage.used_pct >= cfg.storage_alert_pct),
        }
    return data


def pending_sd_bytes(conn: sqlite3.Connection) -> int:
    """Kept items that still exist only on internal storage."""
    return conn.execute(
        "SELECT coalesce(sum(f.size_bytes), 0) FROM files f JOIN items i ON i.id = f.item_id "
        "WHERE i.state = 'library' AND f.root = 'main' AND f.rel_path IS NOT NULL").fetchone()[0]


def set_important(conn: sqlite3.Connection, item_id: int, value: bool) -> None:
    _item(conn, item_id)
    conn.execute("UPDATE items SET important = ? WHERE id = ?", (int(value), item_id))


def purge_expired(cfg: Config, actor: str = "server") -> int:
    """Delete for good what has been in the trash for `trash_days` (rule 6)."""
    conn = db.connect(cfg.db_path)
    purged = 0
    try:
        cutoff = iso_in(-cfg.trash_days)
        rows = conn.execute(
            "SELECT id, sha256 FROM items WHERE state = 'trash' AND trashed_at <= ?", (cutoff,)
        ).fetchall()
        for row in rows:
            files = _files(conn, row["id"])
            with transaction(conn):
                conn.execute(
                    "UPDATE items SET state = 'purged', purged_at = ?, trashed_at = NULL, "
                    "state_before_trash = NULL WHERE id = ? AND state = 'trash' AND trashed_at <= ?",
                    (now_iso(), row["id"], cutoff),
                )
                if conn.execute("SELECT changes()").fetchone()[0] != 1:
                    continue
                for f in files:
                    conn.execute("UPDATE files SET rel_path = NULL WHERE id = ?", (f["id"],))
                    log_event(conn, actor, "purge", item_id=row["id"], file_id=f["id"], sha256=f["sha256"],
                              from_path=f"{f['root']}:{f['rel_path']}",
                              details={"reason": f"{cfg.trash_days} dias na lixeira"})
                conn.execute("DELETE FROM jobs WHERE item_id = ?", (row["id"],))
            # After COMMIT: if we die here, reconcile() removes the leftover (its hash is purged).
            for f in files:
                if f["rel_path"]:
                    (cfg.root_dir(f["root"]) / f["rel_path"]).unlink(missing_ok=True)
            preview_path(cfg, row["sha256"]).unlink(missing_ok=True)  # cache; thumbnails are never deleted
            purged += 1
    finally:
        conn.close()
    if purged:
        log.info("Lixeira: %d itens apagados de vez", purged)
    return purged


def resolve_suggestions(conn: sqlite3.Connection) -> None:
    """A suggestion is done when none of its items is still waiting in the Entrada."""
    conn.execute(
        """UPDATE suggestions SET status = 'resolved', resolved_at = ?
           WHERE status = 'open' AND NOT EXISTS (
               SELECT 1 FROM suggestion_items si JOIN items i ON i.id = si.item_id
               WHERE si.suggestion_id = suggestions.id AND i.state = 'inbox')""",
        (now_iso(),),
    )


ACTIONS = {
    "keep": keep,
    "discard": discard,
    "restore": restore,
}


def apply_action(cfg: Config, item_ids: list[int], action: str, actor: str = "web") -> dict:
    if action not in (*ACTIONS, "important", "unimportant"):
        raise ActionError(f"Ação desconhecida: {action}")
    ok, failed = [], []
    conn = db.connect(cfg.db_path)
    try:
        for iid in item_ids:
            try:
                if action in ACTIONS:
                    ACTIONS[action](cfg, conn, iid, actor)
                else:
                    set_important(conn, iid, action == "important")
                ok.append(iid)
            except (ActionError, OSError, sqlite3.Error, ValueError) as exc:
                log.warning("Ação %s falhou no item %s: %s", action, iid, exc)
                failed.append({"id": iid, "error": str(exc) if isinstance(exc, ActionError) else "Falha ao mover o arquivo."})
        resolve_suggestions(conn)
    finally:
        conn.close()
    return {"ok": ok, "failed": failed}
