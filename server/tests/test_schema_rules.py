"""The catalog itself enforces the safety rules, so a bug in later phases
cannot silently lose a file. These tests pin that behaviour down."""

import sqlite3

import pytest

from conftest import SHA_A, SHA_B, insert_file, insert_item

NOW = "2026-01-01T00:00:00.000Z"
VOL = "7d3f8a8e-0000-4000-8000-000000000001"


def add_volume(conn):
    conn.execute(
        "INSERT INTO volumes (id, name, capacity_bytes) VALUES (?, 'VOLUME-001', 1000000000000)", (VOL,)
    )


# --- rule 4: identical content is stored once -------------------------------

def test_same_content_cannot_be_two_items(conn):
    insert_item(conn, SHA_A, original_name="IMG_1.HEIC")
    with pytest.raises(sqlite3.IntegrityError):
        insert_item(conn, SHA_A, original_name="renomeado.HEIC")


def test_same_content_cannot_be_two_files(conn):
    a = insert_item(conn, SHA_A)
    b = insert_item(conn, SHA_B)
    insert_file(conn, a, SHA_A, "entrada/a.heic")
    with pytest.raises(sqlite3.IntegrityError):
        insert_file(conn, b, SHA_A, "entrada/b.heic")


def test_same_name_different_content_is_fine(conn):
    insert_item(conn, SHA_A, original_name="IMG_1.HEIC")
    insert_item(conn, SHA_B, original_name="IMG_1.HEIC")


# --- states ------------------------------------------------------------------

def test_new_items_land_in_inbox(conn):
    item = insert_item(conn)
    assert conn.execute("SELECT state FROM items WHERE id = ?", (item,)).fetchone()[0] == "inbox"


def test_inbox_cannot_jump_to_purged(conn):
    item = insert_item(conn)
    with pytest.raises(sqlite3.IntegrityError, match="transition"):
        conn.execute("UPDATE items SET state = 'purged', purged_at = ? WHERE id = ?", (NOW, item))


def test_trash_then_purge_is_allowed(conn):
    item = insert_item(conn)
    conn.execute(
        "UPDATE items SET state = 'trash', trashed_at = ?, state_before_trash = 'inbox' WHERE id = ?", (NOW, item)
    )
    conn.execute(
        "UPDATE items SET state = 'purged', purged_at = ?, trashed_at = NULL, state_before_trash = NULL "
        "WHERE id = ?",
        (NOW, item),
    )


def test_purged_is_final(conn):
    item = insert_item(conn)
    conn.execute(
        "UPDATE items SET state = 'trash', trashed_at = ?, state_before_trash = 'inbox' WHERE id = ?", (NOW, item)
    )
    conn.execute(
        "UPDATE items SET state = 'purged', purged_at = ?, trashed_at = NULL, state_before_trash = NULL "
        "WHERE id = ?",
        (NOW, item),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE items SET state = 'library', purged_at = NULL WHERE id = ?", (item,))


def test_trash_requires_timestamp(conn):
    item = insert_item(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE items SET state = 'trash' WHERE id = ?", (item,))


def test_items_are_never_deleted(conn):
    item = insert_item(conn)
    with pytest.raises(sqlite3.IntegrityError, match="never deleted"):
        conn.execute("DELETE FROM items WHERE id = ?", (item,))


# --- rule 3: nothing leaves the server without a verified copy ----------------

def test_server_copy_cannot_be_dropped_without_verified_copy(conn):
    item = insert_item(conn)
    f = insert_file(conn, item)
    with pytest.raises(sqlite3.IntegrityError, match="verified copy"):
        conn.execute("UPDATE files SET rel_path = NULL WHERE id = ?", (f,))


def test_unverified_drive_copy_is_not_enough(conn):
    add_volume(conn)
    item = insert_item(conn)
    f = insert_file(conn, item)
    conn.execute("INSERT INTO volume_copies (file_id, volume_id, rel_path) VALUES (?, ?, 'x')", (f, VOL))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE files SET rel_path = NULL WHERE id = ?", (f,))


def test_verified_drive_copy_allows_archiving(conn):
    add_volume(conn)
    item = insert_item(conn)
    f = insert_file(conn, item)
    conn.execute("UPDATE items SET state = 'library' WHERE id = ?", (item,))

    with pytest.raises(sqlite3.IntegrityError, match="verified copy"):
        conn.execute("UPDATE items SET state = 'archived', volume_id = ? WHERE id = ?", (VOL, item))

    conn.execute(
        "INSERT INTO volume_copies (file_id, volume_id, rel_path, verified_at) VALUES (?, ?, 'x', ?)",
        (f, VOL, NOW),
    )
    conn.execute("UPDATE items SET state = 'archived', volume_id = ? WHERE id = ?", (VOL, item))
    conn.execute("UPDATE files SET rel_path = NULL WHERE id = ?", (f,))


def test_live_photo_needs_both_files_verified(conn):
    add_volume(conn)
    item = insert_item(conn, is_live_photo=1)
    heic = insert_file(conn, item, SHA_A, "acervo/a.heic")
    insert_file(conn, item, SHA_B, "acervo/a.mov", role="live-video")
    conn.execute("UPDATE items SET state = 'library' WHERE id = ?", (item,))
    conn.execute(
        "INSERT INTO volume_copies (file_id, volume_id, rel_path, verified_at) VALUES (?, ?, 'a.heic', ?)",
        (heic, VOL, NOW),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE items SET state = 'archived', volume_id = ? WHERE id = ?", (VOL, item))


# --- event log ---------------------------------------------------------------

def test_events_are_append_only(conn):
    conn.execute("INSERT INTO events (actor, action, sha256) VALUES ('server', 'move', ?)", (SHA_A,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE events SET action = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM events")


# --- search ------------------------------------------------------------------

def search(conn, q):
    return [r[0] for r in conn.execute("SELECT rowid FROM search_fts WHERE search_fts MATCH ?", (q,))]


def test_search_ignores_accents_and_supports_prefix(conn):
    item = insert_item(conn, place="São Paulo, SP")
    assert search(conn, "sao") == [item]
    assert search(conn, "pau*") == [item]
    assert search(conn, "1234") == [item]  # from IMG_1234.HEIC


def test_search_follows_renames(conn):
    item = insert_item(conn)
    conn.execute("UPDATE items SET standard_name = '2024-05-01_1012_IMG_1234.HEIC' WHERE id = ?", (item,))
    assert search(conn, "2024") == [item]


def test_updated_at_is_touched(conn):
    item = insert_item(conn)
    conn.execute("UPDATE items SET updated_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (item,))
    conn.execute("UPDATE items SET important = 1 WHERE id = ?", (item,))
    assert conn.execute("SELECT updated_at FROM items WHERE id = ?", (item,)).fetchone()[0] > "2000"
