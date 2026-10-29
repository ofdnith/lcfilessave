import sqlite3
from pathlib import Path

import pytest

from acervo import db
from acervo.db import Migration, MigrationError

EXPECTED_TABLES = {
    "volumes", "upload_sessions", "items", "files", "volume_copies", "volume_checks",
    "fingerprints", "dedupe_hits", "suggestions", "suggestion_items", "events", "jobs",
    "settings", "search_fts", "schema_migrations",
}


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_fresh_catalog_reaches_latest_version(tmp_path: Path):
    conn = db.connect(tmp_path / "c.db")
    before, after = db.migrate(conn)
    assert before == 0
    assert after == db.latest_version() == db.schema_version(conn)
    assert EXPECTED_TABLES <= tables(conn)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrate_is_idempotent(tmp_path: Path):
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn)
    v = db.schema_version(conn)
    assert db.migrate(conn) == (v, v)


def test_migrations_files_are_sequential():
    migs = db.load_migrations()
    assert [m.version for m in migs] == list(range(1, len(migs) + 1))


def test_upgrade_takes_backup_first(tmp_path: Path):
    m1 = Migration(1, "one", "CREATE TABLE t (x INTEGER) STRICT;")
    m2 = Migration(2, "two", "ALTER TABLE t ADD COLUMN y INTEGER;")
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn, [m1], backup_dir=tmp_path)
    conn.execute("INSERT INTO t (x) VALUES (42)")
    db.migrate(conn, [m1, m2], backup_dir=tmp_path)

    backup = tmp_path / "catalogo.db.bak-v1"
    assert backup.exists()
    b = sqlite3.connect(backup)
    assert b.execute("SELECT x FROM t").fetchone()[0] == 42
    assert b.execute("PRAGMA user_version").fetchone()[0] == 1
    assert db.schema_version(conn) == 2


def test_failed_migration_rolls_back_completely(tmp_path: Path):
    m1 = Migration(1, "one", "CREATE TABLE t (x INTEGER) STRICT;")
    bad = Migration(2, "bad", "CREATE TABLE u (y INTEGER); THIS IS NOT SQL;")
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn, [m1])
    with pytest.raises(MigrationError):
        db.migrate(conn, [m1, bad])
    assert db.schema_version(conn) == 1
    assert "u" not in tables(conn)


def test_edited_migration_is_refused(tmp_path: Path):
    conn = db.connect(tmp_path / "c.db")
    db.migrate(conn, [Migration(1, "one", "CREATE TABLE t (x INTEGER);")])
    with pytest.raises(MigrationError, match="alterada"):
        db.migrate(conn, [Migration(1, "one", "CREATE TABLE t (x TEXT);")])


def test_newer_catalog_is_refused(tmp_path: Path):
    conn = db.connect(tmp_path / "c.db")
    conn.execute("PRAGMA user_version = 99")
    with pytest.raises(MigrationError, match="mais nova"):
        db.migrate(conn)
