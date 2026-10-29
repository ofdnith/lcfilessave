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

from . import db
from .catalog import free_rel_path, iso_in, library_dir, log_event, now_iso, preview_path, thumb_path, transaction
from .config import INBOX_DIR, TRASH_DIR, Config
from .storage import disk_usage, move_verified

log = logging.getLogger(__name__)


class ActionError(ValueError):
    """Message in Portuguese, shown to the user."""


def choose_root(cfg: Config, size: int) -> str:
    """Internal storage unless it is above the alert level and a microSD with room exists."""
    if cfg.sd_dir is None or not cfg.sd_dir.is_dir():
        return "main"
    if disk_usage(cfg.data_dir).used_pct < cfg.storage_alert_pct:
        return "main"
    return "sd" if disk_usage(cfg.sd_dir).free_bytes > size * 2 + 1_000_000_000 else "main"


def _files(conn: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, role, sha256, rel_path, root FROM files WHERE item_id = ? ORDER BY role = 'live-video'",
        (item_id,),
    ).fetchall()


def _move_files(cfg: Config, conn: sqlite3.Connection, item: sqlite3.Row, root: str, directory: str,
                action: str, actor: str) -> None:
    for f in _files(conn, item["id"]):
        if f["rel_path"] is None:
            raise ActionError("O original não está no servidor.")
        name = f["rel_path"].rsplit("/", 1)[1]
        new_rel = free_rel_path(conn, cfg, root, directory, name)
        conn.execute("UPDATE files SET rel_path = ?, root = ? WHERE id = ?", (new_rel, root, f["id"]))
        log_event(conn, actor, action, item_id=item["id"], file_id=f["id"], sha256=f["sha256"],
                  from_path=f"{f['root']}:{f['rel_path']}", to_path=f"{root}:{new_rel}")
        move_verified(cfg.root_dir(f["root"]) / f["rel_path"], cfg.root_dir(root) / new_rel, f["sha256"])


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
            thumb_path(cfg, row["sha256"]).unlink(missing_ok=True)
            preview_path(cfg, row["sha256"]).unlink(missing_ok=True)
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
            except (ActionError, OSError, sqlite3.Error) as exc:
                log.warning("Ação %s falhou no item %s: %s", action, iid, exc)
                failed.append({"id": iid, "error": str(exc) if isinstance(exc, ActionError) else "Falha ao mover o arquivo."})
        resolve_suggestions(conn)
    finally:
        conn.close()
    return {"ok": ok, "failed": failed}
