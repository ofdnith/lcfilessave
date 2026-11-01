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
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .catalog import (free_rel_path, get_setting, inbox_bytes, iso_in, library_bytes_by_root, library_dir, log_event,
                      now_iso, parse_iso, preview_path, transaction)
from .config import INBOX_DIR, TRASH_DIR, Config
from .storage import VerificationError, copy_verified, disk_usage, fsync_dir, move_verified

log = logging.getLogger(__name__)


class ActionError(ValueError):
    """Message in Portuguese, shown to the user."""


# The microSD card was retired on 01/11/2026: everything new stays on the phone's
# own storage until it goes to an external storage. Files copied to the card
# before that are brought back (verified) by bring_back_from_card().
CARD_MARGIN_BYTES = 1_000_000_000
CARD_BATCH_BYTES = 2_000_000_000  # per bring_back_from_card() call, so the loop stays responsive


def card_available(cfg: Config) -> bool:
    return cfg.sd_dir is not None and cfg.sd_dir.is_dir()


def internal_has_room(cfg: Config, size: int) -> bool:
    """Room on the phone's own storage for `size` bytes more, without crossing the alert level."""
    usage = disk_usage(cfg.data_dir)
    after = 100 * (usage.used_bytes + size) / usage.total_bytes if usage.total_bytes else 100
    return usage.free_bytes > size * 2 + CARD_MARGIN_BYTES and after < cfg.storage_alert_pct


def choose_root(cfg: Config, size: int) -> str:
    """Where a kept item goes at triage time: always the server's own storage."""
    return "main"


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
        raise ActionError("Itens que já estão num armazenamento não podem ir para a lixeira.")
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
                # copy_verified just re-read it: this is also a health check.
                conn.execute("UPDATE files SET rel_path = ?, root = ?, checked_at = ?, check_ok = 1 WHERE id = ?",
                             (new_rel, root, now_iso(), f["id"]))
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


def bring_back_from_card(cfg: Config, actor: str = "server", max_bytes: int = CARD_BATCH_BYTES) -> int:
    """Copy kept items that still live on the retired microSD back to the phone's
    own storage, verified by SHA-256, then free the card copy. Returns how many moved.

    Called in a loop by the worker; `max_bytes` bounds one call. Stops when the
    phone has no room left (those items leave in the next batch to an external
    storage instead, which reads them straight from the card) or at the first
    card error (removed, failing).
    """
    if not card_available(cfg):
        return 0
    conn = db.connect(cfg.db_path)
    moved = done_bytes = 0
    try:
        if get_setting(conn, "migration_active"):
            return 0
        rows = conn.execute(
            "SELECT i.id, sum(f.size_bytes) AS size FROM items i JOIN files f ON f.item_id = i.id "
            "WHERE i.state = 'library' AND f.root = 'sd' AND f.rel_path IS NOT NULL "
            "GROUP BY i.id ORDER BY i.id").fetchall()
        for row in rows:
            if done_bytes and done_bytes + row["size"] > max_bytes:
                break
            if not internal_has_room(cfg, row["size"]):
                log.info("Sem espaço no celular para trazer o resto do cartão: esses itens saem "
                         "do cartão direto no próximo lote para o armazenamento")
                break
            try:
                if _copy_then_switch(cfg, conn, row["id"], "main", "from-sd", actor):
                    moved += 1
                    done_bytes += row["size"]
            except _Changed:
                continue
            except (ActionError, OSError, VerificationError) as exc:
                log.warning("Não consegui trazer o item %s do cartão: %s", row["id"], exc)
                break
    finally:
        conn.close()
    if moved:
        log.info("Cartão microSD: %d itens trazidos de volta e conferidos", moved)
    return moved


def storage_summary(cfg: Config, conn: sqlite3.Connection) -> dict:
    """Entrada limit and reminders, for /api/stats and /api/health."""
    inbox = inbox_bytes(conn)
    limit = cfg.inbox_max_gb * 1_000_000_000
    oldest = conn.execute("SELECT min(uploaded_at) FROM items WHERE state = 'inbox'").fetchone()[0]
    days = int((datetime.now(timezone.utc) - parse_iso(oldest)).total_seconds() // 86400) if oldest else None
    reasons = []
    if cfg.inbox_alert_days and days is not None and days >= cfg.inbox_alert_days:
        reasons.append("dias")
    if cfg.inbox_alert_gb and inbox >= cfg.inbox_alert_gb * 1_000_000_000:
        reasons.append("tamanho")
    data: dict = {
        "inbox_bytes": inbox,
        "inbox_max_bytes": limit or None,
        "inbox_alert": bool(limit) and inbox >= limit * 0.9,
        # Reminder to triage (lighter than inbox_alert): what is in the Entrada is
        # only on the phone, so it should not sit there for long.
        "inbox_oldest_at": oldest,
        "inbox_waiting_days": days,
        "inbox_reminder": {"reasons": reasons, "days": days, "bytes": inbox} if reasons else None,
        # Retired microSD: what is still there (it comes back by itself, see bring_back_from_card).
        "card": None,
    }
    card_bytes = library_bytes_by_root(conn).get("sd", 0)
    if card_bytes or (cfg.sd_dir is not None and card_available(cfg)):
        data["card"] = {"present": card_available(cfg), "library_bytes": card_bytes}
    return data


def _gb(n: int) -> str:
    return f"{n / 1e9:.{0 if n >= 10e9 else 1}f}".replace(".", ",")


def _days(n: int) -> str:
    return f"{n} dia{'s' if n != 1 else ''}"


def pending_archive(cfg: Config, conn: sqlite3.Connection) -> dict:
    """Kept items (Acervo) whose original is still on the server: the next batch."""
    size, oldest = conn.execute(
        "SELECT coalesce(sum(f.size_bytes), 0), min(i.uploaded_at) FROM files f JOIN items i ON i.id = f.item_id "
        "WHERE i.state = 'library' AND f.rel_path IS NOT NULL").fetchone()
    days = int((datetime.now(timezone.utc) - parse_iso(oldest)).total_seconds() // 86400) if oldest else None
    return {"bytes": size, "oldest_days": days}


def alerts(cfg: Config, conn: sqlite3.Connection, daily_overdue: bool = False) -> list[dict]:
    """Everything the owner should act on, most urgent first. The same texts go to
    the app (banners) and to the iPhone notifications (`topic`).

    Since the microSD was retired, the phone's own storage holds the Entrada and
    the Acervo until a batch goes to an external storage; until then, those
    files exist only on the phone. The alerts follow that: space on the phone,
    a batch waiting for an external storage, the Entrada waiting for triage,
    the daily backup."""
    out: list[dict] = []
    summary = storage_summary(cfg, conn)
    usage = disk_usage(cfg.data_dir)
    batch = pending_archive(cfg, conn)
    budget = cfg.archive_batch_gb * 1_000_000_000
    if usage.used_pct >= cfg.storage_alert_pct:
        critical = usage.used_pct >= 95 or usage.free_bytes < 3_000_000_000
        out.append({
            "id": "espaco", "topic": "espaco", "level": "danger" if critical else "warn",
            "title": "Pouco espaço no celular do Acervo",
            "text": f"{usage.used_pct:.0f}% ocupado, {_gb(usage.free_bytes)} GB livres."
                    + (" Novos envios vão parar quando acabar." if critical else "")
                    + (" Transfira um lote para um armazenamento" if batch["bytes"] else " Faça a triagem da Entrada")
                    + " para liberar espaço.",
            "href": "/#/dispositivos" if batch["bytes"] else "/#/entrada",
        })
    by_size = batch["bytes"] >= budget
    by_age = bool(cfg.archive_alert_days and batch["bytes"] and batch["oldest_days"] is not None
                  and batch["oldest_days"] >= cfg.archive_alert_days)
    if by_size or by_age:
        why = (f"{_gb(batch['bytes'])} GB do Acervo"
               + (f", o mais antigo há {_days(batch['oldest_days'])}," if by_age else "")
               + " só existem no celular.")
        out.append({
            "id": "lote", "topic": "lote", "level": "warn",
            "title": "Lote pronto para o armazenamento",
            "text": why + " Conecte um armazenamento no computador e use Transferir lote, no app do Acervo.",
            "href": "/#/dispositivos",
        })
    reminder = summary["inbox_reminder"]
    if reminder:
        out.append({"id": "entrada", "topic": "entrada", "level": "info", "title": "Entrada esperando triagem",
                    "text": inbox_reminder_text(reminder), "href": "/#/entrada"})
    if daily_overdue:
        out.append({"id": "backup_atrasado", "topic": "backup_atrasado", "level": "warn",
                    "title": "Backup diário atrasado",
                    "text": "O iPhone não manda fotos há mais de 48 horas. Confira a automação do Atalhos.",
                    "href": "/#/ajuda/backup-diario"})
    card = summary["card"]
    if card and card["library_bytes"] and not card["present"]:
        out.append({"id": "cartao", "topic": None, "level": "danger", "title": "Cartão microSD não encontrado",
                    "text": f"{_gb(card['library_bytes'])} GB do Acervo ainda estão no cartão antigo. Coloque o cartão "
                            "de volta até eles voltarem para o celular (acontece sozinho).",
                    "href": "/#/ajuda/cartao"})
    return out


def inbox_reminder_text(reminder: dict) -> str:
    gb = f"{reminder['bytes'] / 1e9:.1f}".replace(".", ",")
    days = reminder["days"]
    parts = [f"{gb} GB na Entrada"]
    if days:
        parts.append(f"a mais antiga chegou há {days} dia{'s' if days != 1 else ''}")
    return " · ".join(parts) + ". Até a triagem, isso só existe no celular."


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
