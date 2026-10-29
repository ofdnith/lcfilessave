"""Browsing, search, media files, triage actions, suggestions, stats."""

from __future__ import annotations

import re
import sqlite3
from datetime import date as _date
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import __version__, auth, db, library, media, power
from ..catalog import ITEM_COLUMNS, ITEM_FROM, get_setting, iso_in, item_json, medium_path, now_iso, thumb_path
from ..jobs import preview_for
from ..storage import disk_usage

router = APIRouter(prefix="/api", dependencies=[Depends(auth.require_auth)])

VIEWS = {"library": ("library", "archived"), "inbox": ("inbox",), "trash": ("trash",)}
KINDS = ("photo", "video", "document", "audio", "other")
_WORD = re.compile(r"\w+", re.UNICODE)
_PART = re.compile(r"[^\W_]+", re.UNICODE)  # how the FTS tokenizer splits: "IMG_1234" -> img, 1234


def _conn(request: Request) -> sqlite3.Connection:
    return db.connect(request.app.state.config.db_path)


def fts_query(q: str) -> str | None:
    """'img_12 praia' -> '"img" + "12"* AND "praia"*': each typed word is a phrase of
    its parts (so a file name matches in order), the last part as a prefix."""
    terms = []
    for word in _WORD.findall(q)[:12]:
        parts = _PART.findall(word)
        if parts:
            terms.append(" + ".join(f'"{p}"' for p in parts) + "*")
    return " AND ".join(terms) or None


def _filters(view: str, kind: str, q: str | None, year: int | None, month: int | None,
             important: int | None, archived: int | None, place: str | None = None,
             album_id: int | None = None) -> tuple[list[str], list]:
    if view not in VIEWS:
        raise HTTPException(400, "view inválida")
    # An album shows its items wherever they are (Entrada, Acervo or a drive).
    states = ("inbox", "library", "archived") if album_id else VIEWS[view]
    where = [f"i.state IN ({','.join('?' * len(states))})"]
    args: list = list(states)
    if kind != "all":
        if kind not in KINDS:
            raise HTTPException(400, "kind inválido")
        where.append("i.kind = ?")
        args.append(kind)
    if q:
        match = fts_query(q)
        if match:
            where.append("i.id IN (SELECT rowid FROM search_fts WHERE search_fts MATCH ?)")
            args.append(match)
    if year:
        prefix = f"{year:04d}-{month:02d}" if month else f"{year:04d}"
        where.append("i.captured_at LIKE ?")
        args.append(prefix + "%")
    if important:
        where.append("i.important = 1")
    if archived is not None:
        where.append("i.state = 'archived'" if archived else "i.state <> 'archived'")
    if place:
        where.append("i.place = ?")
        args.append(place)
    if album_id:
        where.append("i.id IN (SELECT item_id FROM album_items WHERE album_id = ?)")
        args.append(album_id)
    return where, args


@router.get("/items")
def list_items(request: Request, view: str = "library", kind: str = "all", q: str | None = None,
               year: int | None = None, month: int | None = Query(None, ge=1, le=12),
               start: str | None = None, important: int | None = None, archived: int | None = None,
               place: str | None = None, album_id: int | None = None, ids: str | None = None,
               cursor: str | None = None, limit: int = Query(200, ge=1, le=500)) -> dict:
    cfg = request.app.state.config
    where, args = _filters(view, kind, q, year, month, important, archived, place, album_id)
    if ids:
        wanted = [int(x) for x in ids.split(",") if x.strip().isdigit()][:500]
        if not wanted:
            raise HTTPException(400, "ids inválidos")
        where = ["i.state IN ('inbox', 'library', 'archived')", f"i.id IN ({','.join('?' * len(wanted))})"]
        args = wanted
    order_col = "i.trashed_at" if view == "trash" else "i.captured_at"
    total_where, total_args = list(where), list(args)
    if start:
        m = re.fullmatch(r"(\d{4})-(\d{2})", start)
        if not m:
            raise HTTPException(400, "start deve ser AAAA-MM")
        y, mo = int(m.group(1)), int(m.group(2))
        nxt = f"{y + (mo == 12):04d}-{(mo % 12) + 1:02d}"
        where.append("i.captured_at < ?")
        args.append(nxt)
    if cursor:
        value, _, cid = cursor.rpartition("|")
        if not cid.isdigit():
            raise HTTPException(400, "cursor inválido")
        where.append(f"({order_col} < ? OR ({order_col} = ? AND i.id < ?))")
        args += [value, value, int(cid)]
    conn = _conn(request)
    try:
        rows = conn.execute(
            f"SELECT {ITEM_COLUMNS}, {order_col} AS sort_key FROM {ITEM_FROM} WHERE {' AND '.join(where)} "
            f"ORDER BY {order_col} DESC, i.id DESC LIMIT ?", (*args, limit + 1)).fetchall()
        total = conn.execute(f"SELECT count(*) FROM items i WHERE {' AND '.join(total_where)}", total_args).fetchone()[0]
    finally:
        conn.close()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [item_json(r, cfg) for r in rows],
        "next_cursor": f"{rows[-1]['sort_key']}|{rows[-1]['id']}" if more and rows else None,
        "total": total,
    }


@router.get("/timeline")
def timeline(request: Request, view: str = "library", kind: str = "all", q: str | None = None,
             important: int | None = None, archived: int | None = None, place: str | None = None,
             album_id: int | None = None) -> dict:
    where, args = _filters(view, kind, q, None, None, important, archived, place, album_id)
    conn = _conn(request)
    try:
        rows = conn.execute(
            f"SELECT substr(i.captured_at, 1, 7) AS ym, count(*) AS n FROM items i WHERE {' AND '.join(where)} "
            f"GROUP BY ym ORDER BY ym DESC", args).fetchall()
    finally:
        conn.close()
    return {"months": [{"year": int(r["ym"][:4]), "month": int(r["ym"][5:7]), "count": r["n"]} for r in rows]}


def _get_item(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row:
    row = conn.execute(f"SELECT {ITEM_COLUMNS} FROM {ITEM_FROM} WHERE i.id = ? AND i.state <> 'purged'",
                       (item_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Item não encontrado")
    return row


@router.get("/items/{item_id}")
def get_item(item_id: int, request: Request) -> dict:
    cfg = request.app.state.config
    conn = _conn(request)
    try:
        row = _get_item(conn, item_id)
        data = item_json(row, cfg)
        files = []
        for f in conn.execute("SELECT id, role, size_bytes, mime, rel_path FROM files WHERE item_id = ? "
                              "ORDER BY role = 'live-video'", (item_id,)):
            copies = conn.execute(
                "SELECT v.id, v.name, vc.rel_path FROM volume_copies vc JOIN volumes v ON v.id = vc.volume_id "
                "WHERE vc.file_id = ? AND vc.verified_at IS NOT NULL ORDER BY v.name", (f["id"],)).fetchall()
            on_item_volume = next((c["rel_path"] for c in copies if c["id"] == row["volume_id"]), None)
            files.append({"id": f["id"], "role": f["role"], "size_bytes": f["size_bytes"], "mime": f["mime"],
                          "on_server": f["rel_path"] is not None, "volumes": [c["name"] for c in copies],
                          # path on the drive (the item's volume, else the first one holding it)
                          "rel_path": on_item_volume or (copies[0]["rel_path"] if copies else None),
                          "drive_copies": [{"volume": c["name"], "rel_path": c["rel_path"]} for c in copies]})
        data["files"] = files
        data["albums"] = [dict(r) for r in conn.execute(
            "SELECT a.id, a.name FROM albums a JOIN album_items ai ON ai.album_id = a.id "
            "WHERE ai.item_id = ? ORDER BY a.name", (item_id,))]
        data["suggestions"] = [dict(r) for r in conn.execute(
            "SELECT s.id, s.kind FROM suggestions s JOIN suggestion_items si ON si.suggestion_id = s.id "
            "WHERE si.item_id = ? AND s.status = 'open'", (item_id,))]
    finally:
        conn.close()
    return data


IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}


@router.get("/items/{item_id}/thumb")
def thumb(item_id: int, request: Request) -> FileResponse:
    cfg = request.app.state.config
    conn = _conn(request)
    try:
        row = conn.execute("SELECT sha256 FROM items WHERE id = ? AND state <> 'purged'", (item_id,)).fetchone()
    finally:
        conn.close()
    path = thumb_path(cfg, row["sha256"]) if row else None
    if path is None or not path.exists():
        raise HTTPException(404, "Miniatura ainda não existe")
    return FileResponse(path, media_type="image/webp", headers=IMMUTABLE)


@router.get("/items/{item_id}/medium")
def medium(item_id: int, request: Request) -> FileResponse:
    cfg = request.app.state.config
    conn = _conn(request)
    try:
        row = conn.execute("SELECT sha256 FROM items WHERE id = ? AND state <> 'purged'", (item_id,)).fetchone()
    finally:
        conn.close()
    path = medium_path(cfg, row["sha256"]) if row else None
    if path is None or not path.exists():
        raise HTTPException(404, "Prévia ainda não existe")
    return FileResponse(path, media_type="image/webp", headers=IMMUTABLE)


def _file_for(conn: sqlite3.Connection, request: Request, item_id: int, role: str):
    cfg = request.app.state.config
    row = conn.execute(
        "SELECT i.*, f.rel_path, f.root, f.ext, f.mime AS file_mime, v.name AS volume_name FROM items i "
        "JOIN files f ON f.item_id = i.id AND f.role = ? LEFT JOIN volumes v ON v.id = i.volume_id "
        "WHERE i.id = ? AND i.state <> 'purged'", (role, item_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Arquivo não encontrado")
    if row["rel_path"] is None:
        raise HTTPException(410, {"error": f"Original no {row['volume_name']}", "volume": row["volume_name"]})
    path = cfg.root_dir(row["root"]) / row["rel_path"]
    if not path.exists():
        raise HTTPException(404, "Arquivo sumiu do disco; rode a verificação do servidor")
    return row, path


@router.get("/items/{item_id}/original")
def original(item_id: int, request: Request, role: str = "original", download: int = 0) -> FileResponse:
    if role not in ("original", "live-video"):
        raise HTTPException(400, "role inválido")
    conn = _conn(request)
    try:
        row, path = _file_for(conn, request, item_id, role)
    finally:
        conn.close()
    name = row["original_name"] if role == "original" else path.name
    return FileResponse(path, media_type=row["file_mime"] or "application/octet-stream", filename=name,
                        content_disposition_type="attachment" if download else "inline")


@router.get("/items/{item_id}/preview")
async def preview(item_id: int, request: Request) -> FileResponse:
    state = request.app.state
    conn = _conn(request)
    try:
        row, path = _file_for(conn, request, item_id, "original")
    finally:
        conn.close()
    mime = row["file_mime"] or ""
    if row["kind"] == "photo" and mime not in media.BROWSER_IMAGE_MIME:
        try:
            path = await run_in_threadpool(preview_for, state.config, state.exiftool, row, path)
        except media.CannotRender:
            raise HTTPException(415, "Não foi possível gerar a prévia") from None
        return FileResponse(path, media_type="image/jpeg", headers=IMMUTABLE)
    return FileResponse(path, media_type=mime or "application/octet-stream")


# --- triage in one tap ----------------------------------------------------------------

FLAGGED = ("EXISTS (SELECT 1 FROM suggestion_items si JOIN suggestions s ON s.id = si.suggestion_id "
           "WHERE si.item_id = items.id AND s.status = 'open')")


@router.get("/inbox/summary")
def inbox_summary(request: Request) -> dict:
    conn = _conn(request)
    try:
        library.resolve_suggestions(conn)
        total = conn.execute("SELECT count(*) FROM items WHERE state = 'inbox'").fetchone()[0]
        flagged = conn.execute(f"SELECT count(*) FROM items WHERE state = 'inbox' AND {FLAGGED}").fetchone()[0]
    finally:
        conn.close()
    return {"total": total, "flagged": flagged, "clean": total - flagged}


@router.post("/inbox/keep-clean")
async def inbox_keep_clean(request: Request) -> dict:
    cfg = request.app.state.config
    conn = _conn(request)
    try:
        ids = [r[0] for r in conn.execute(f"SELECT id FROM items WHERE state = 'inbox' AND NOT {FLAGGED}")]
    finally:
        conn.close()
    result = await run_in_threadpool(library.apply_action, cfg, ids, "keep", "web") if ids else {"ok": [], "failed": []}
    left = inbox_summary(request)["total"]
    return {"kept": len(result["ok"]), "flagged_left": left}


# --- memories, places, map ---------------------------------------------------------------

@router.get("/memories")
def memories(request: Request, date: str | None = None) -> dict:
    cfg = request.app.state.config
    if date is None:
        date = _date.today().strftime("%m-%d")
    if not re.fullmatch(r"\d{2}-\d{2}", date):
        raise HTTPException(400, "date deve ser MM-DD")
    this_year = _date.today().year
    conn = _conn(request)
    try:
        rows = conn.execute(
            f"SELECT {ITEM_COLUMNS} FROM {ITEM_FROM} WHERE i.state IN ('library', 'archived') "
            f"AND i.kind IN ('photo', 'video') AND substr(i.captured_at, 6, 5) = ? "
            f"AND CAST(substr(i.captured_at, 1, 4) AS INTEGER) < ? AND i.date_source <> 'upload' "
            f"ORDER BY i.captured_at DESC", (date, this_year)).fetchall()
    finally:
        conn.close()
    years: dict[int, list] = {}
    for r in rows:
        years.setdefault(int(r["captured_at"][:4]), []).append(r)
    out = []
    for year in sorted(years, reverse=True):
        group = sorted(years[year], key=lambda r: (not r["important"], r["captured_at"]))
        out.append({"year": year, "years_ago": this_year - year, "count": len(group),
                    "items": [item_json(r, cfg) for r in group[:30]]})
    return {"date": date, "years": out}


@router.get("/places")
def places(request: Request) -> dict:
    cfg = request.app.state.config
    conn = _conn(request)
    try:
        rows = conn.execute(
            "SELECT place, count(*) AS n, avg(gps_lat) AS lat, avg(gps_lon) AS lon, "
            "(SELECT x.id FROM items x WHERE x.place = items.place AND x.state IN ('library', 'archived') "
            " ORDER BY x.important DESC, x.thumb_status = 'ok' DESC, x.captured_at DESC LIMIT 1) AS cover "
            "FROM items WHERE place IS NOT NULL AND state IN ('library', 'archived') "
            "GROUP BY place ORDER BY n DESC LIMIT 500").fetchall()
        covers = {}
        ids = [r["cover"] for r in rows if r["cover"]]
        if ids:
            marks = ",".join("?" * len(ids))
            covers = {r["id"]: item_json(r, cfg) for r in conn.execute(
                f"SELECT {ITEM_COLUMNS} FROM {ITEM_FROM} WHERE i.id IN ({marks})", ids)}
    finally:
        conn.close()
    return {"places": [{"place": r["place"], "count": r["n"], "lat": round(r["lat"], 5) if r["lat"] is not None else None,
                        "lon": round(r["lon"], 5) if r["lon"] is not None else None,
                        "cover": covers.get(r["cover"])} for r in rows]}


@router.get("/map/points")
def map_points(request: Request) -> dict:
    conn = _conn(request)
    try:
        rows = conn.execute("SELECT id, gps_lat, gps_lon FROM items WHERE gps_lat IS NOT NULL "
                            "AND state IN ('library', 'archived') ORDER BY captured_at DESC").fetchall()
    finally:
        conn.close()
    return {"points": [[r[0], r[1], r[2]] for r in rows]}


class ActionBody(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=5000)
    action: str


@router.post("/items/actions")
async def actions(body: ActionBody, request: Request) -> dict:
    cfg = request.app.state.config
    if body.action == "discard":
        auth.forbid_remote(request)
    try:
        return await run_in_threadpool(library.apply_action, cfg, body.ids, body.action, "web")
    except library.ActionError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/trash/purge-expired", dependencies=[Depends(auth.forbid_remote)])
async def purge(request: Request) -> dict:
    return {"purged": await run_in_threadpool(library.purge_expired, request.app.state.config, "web")}


@router.get("/suggestions")
def suggestions(request: Request, status: str = "open") -> dict:
    cfg = request.app.state.config
    conn = _conn(request)
    try:
        library.resolve_suggestions(conn)
        out = []
        for s in conn.execute("SELECT id, kind, created_at FROM suggestions WHERE status = ? "
                              "ORDER BY created_at DESC LIMIT 200", (status,)):
            rows = conn.execute(
                f"SELECT {ITEM_COLUMNS} FROM {ITEM_FROM} JOIN suggestion_items si ON si.item_id = i.id "
                f"WHERE si.suggestion_id = ? AND i.state IN ('inbox', 'library', 'archived') "
                f"ORDER BY i.captured_at DESC", (s["id"],)).fetchall()
            if rows:
                out.append({"id": s["id"], "kind": s["kind"], "created_at": s["created_at"],
                            "items": [item_json(r, cfg) for r in rows]})
    finally:
        conn.close()
    return {"suggestions": out}


@router.post("/suggestions/{suggestion_id}/dismiss")
def dismiss(suggestion_id: int, request: Request) -> dict:
    conn = _conn(request)
    try:
        cur = conn.execute("UPDATE suggestions SET status = 'dismissed', resolved_at = ? WHERE id = ? "
                           "AND status = 'open'", (now_iso(), suggestion_id))
    finally:
        conn.close()
    return {"ok": cur.rowcount == 1}


def _tab_stats(conn: sqlite3.Connection, states: tuple[str, ...]) -> dict:
    tabs = {k: {"count": 0, "bytes": 0} for k in ("all", *KINDS)}
    for r in conn.execute(f"SELECT kind, count(*), coalesce(sum(size_bytes), 0) FROM items "
                          f"WHERE state IN ({','.join('?' * len(states))}) GROUP BY kind", states):
        tabs[r[0]] = {"count": r[1], "bytes": r[2]}
        tabs["all"]["count"] += r[1]
        tabs["all"]["bytes"] += r[2]
    return tabs


REPAIR_WINDOW_DAYS = 3


def daily_status(conn: sqlite3.Connection) -> dict:
    last = get_setting(conn, "last_daily_backup_at")
    since = iso_in(-1, last) if last else iso_in(-7)
    repair = repair_since(conn)
    return {"last_at": last, "overdue": bool(last and last < iso_in(-2)),
            "since": min(since, repair) if repair else since, "repairing": repair is not None}


def repair_since(conn: sqlite3.Connection) -> str | None:
    """A copy on the server failed its health check and the photo came from the
    iPhone (and was not emptied from it): reach back far enough that the daily
    backup sends it again — the upload then repairs it. The Shortcut fetches
    photos created after `since`, oldest first, so starting an hour before the
    oldest damaged photo puts it among the first ones. Only for a few days after
    the failure, so a photo no longer on the iPhone does not make every backup
    re-send hundreds of old photos forever."""
    rows = conn.execute(
        "SELECT i.captured_at, i.captured_tz FROM files f JOIN items i ON i.id = f.item_id "
        "WHERE f.check_ok = 0 AND f.rel_path IS NOT NULL AND f.checked_at >= ? "
        "AND i.source IN ('iphone-daily', 'iphone-manual')", (iso_in(-REPAIR_WINDOW_DAYS),)).fetchall()
    stamps = []
    for r in rows:
        try:
            dt = datetime.fromisoformat(r["captured_at"] + (r["captured_tz"] or ""))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.astimezone()  # server's local time, like the iPhone's
        stamps.append(dt.astimezone(timezone.utc))
    if not stamps:
        return None
    return (min(stamps) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@router.get("/stats")
def stats(request: Request) -> dict:
    cfg = request.app.state.config
    conn = _conn(request)
    try:
        count = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731
        server_bytes = count("SELECT coalesce(sum(size_bytes), 0) FROM files WHERE rel_path IS NOT NULL")
        recent = count("SELECT coalesce(sum(size_bytes), 0) FROM items WHERE uploaded_at >= ? "
                       "AND state <> 'purged'", iso_in(-28))
        data = {
            "inbox_count": count("SELECT count(*) FROM items WHERE state = 'inbox'"),
            "trash_count": count("SELECT count(*) FROM items WHERE state = 'trash'"),
            "archived_count": count("SELECT count(*) FROM items WHERE state = 'archived'"),
            "suggestions_open": count("SELECT count(*) FROM suggestions WHERE status = 'open'"),
            "tabs": _tab_stats(conn, ("library", "archived")),
            "inbox_tabs": _tab_stats(conn, ("inbox",)),
            "daily_backup": daily_status(conn),
        }
        summary = library.storage_summary(cfg, conn)
    finally:
        conn.close()
    usage = disk_usage(cfg.data_dir)
    budget = cfg.archive_batch_gb * 1_000_000_000
    weekly = recent / 4
    data["storage"] = {
        "server_bytes": server_bytes,
        "budget_bytes": budget,
        "disk_total_bytes": usage.total_bytes,
        "disk_free_bytes": usage.free_bytes,
        "used_pct": usage.used_pct,
        "alert": usage.used_pct >= cfg.storage_alert_pct or server_bytes >= budget,
        "weeks_to_next_drive": _weeks(budget - server_bytes, weekly),
        **summary,
    }
    return data


def _weeks(remaining: int, weekly: float) -> float | None:
    """Weeks until the batch budget fills, at the last 4 weeks' pace; None if > 2 years or unknown."""
    if weekly <= 0:
        return None
    weeks = max(0, remaining) / weekly
    return round(weeks, 1) if weeks <= 104 else None


@router.get("/daily")
def daily(request: Request) -> dict:
    conn = _conn(request)
    try:
        return daily_status(conn)
    finally:
        conn.close()


@router.get("/settings")
def settings(request: Request) -> dict:
    cfg = request.app.state.config
    return {"archive_batch_gb": cfg.archive_batch_gb, "trash_days": cfg.trash_days,
            "archive_copies": cfg.archive_copies, "server_name": cfg.server_name, "version": __version__,
            "battery": power.battery(), "inbox_max_gb": cfg.inbox_max_gb,
            "sd_for_library": cfg.sd_for_library, "thermal": _thermal(request)}


def _thermal(request: Request) -> dict | None:
    worker = getattr(request.app.state, "worker", None)
    return worker.thermal.status() if worker is not None else None

