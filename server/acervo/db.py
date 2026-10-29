"""SQLite connection and schema migrations.

Migrations are plain SQL files in acervo/migrations named NNNN_description.sql.
The schema version is PRAGMA user_version. Each migration runs in a single
transaction together with the version bump, so a crash (Android "signal 9")
leaves the catalog either fully before or fully after a migration.

Before upgrading an existing catalog, a consistent copy is written next to it
(catalogo.db.bak-v<old version>) using SQLite's online backup API.

Applied migrations are recorded with a checksum; editing a migration that was
already applied is refused, because the catalog would no longer match the code.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

log = logging.getLogger(__name__)

_MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
MIN_SQLITE = (3, 37, 0)  # STRICT tables


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode()).hexdigest()


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open the catalog with the settings every connection must have."""
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise MigrationError(
            f"SQLite {sqlite3.sqlite_version} é antigo demais; o Acervo precisa de 3.37 ou mais novo."
        )
    # isolation_level=None: we control transactions explicitly (BEGIN … COMMIT).
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    # FULL: a committed change survives even a power cut. The catalog is the
    # source of truth for what may be deleted, so durability beats speed here.
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def load_migrations() -> list[Migration]:
    found = []
    for entry in resources.files("acervo.migrations").iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            found.append(Migration(int(m.group(1)), m.group(2), entry.read_text("utf-8")))
    found.sort(key=lambda mig: mig.version)
    for expected, mig in enumerate(found, start=1):
        if mig.version != expected:
            raise MigrationError(f"Migrações fora de sequência: esperava {expected:04d}, achei {mig.version:04d}")
    return found


def latest_version(migrations: list[Migration] | None = None) -> int:
    migrations = load_migrations() if migrations is None else migrations
    return migrations[-1].version if migrations else 0


def migrate(conn: sqlite3.Connection, migrations: list[Migration] | None = None,
            backup_dir: Path | None = None) -> tuple[int, int]:
    """Bring the catalog up to date. Returns (version_before, version_after)."""
    migrations = load_migrations() if migrations is None else migrations
    target = latest_version(migrations)

    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version    INTEGER PRIMARY KEY,
               name       TEXT NOT NULL,
               checksum   TEXT NOT NULL,
               applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
           ) STRICT"""
    )
    current = schema_version(conn)

    if current > target:
        raise MigrationError(
            f"O catálogo está na versão {current}, mais nova que este código ({target}). "
            "Atualize o Acervo antes de abrir este catálogo."
        )
    _verify_applied(conn, migrations[:current])

    pending = [m for m in migrations if m.version > current]
    if not pending:
        return current, current

    if current > 0 and backup_dir is not None:
        _backup(conn, backup_dir / f"catalogo.db.bak-v{current}")

    for mig in pending:
        log.info("Aplicando migração %04d_%s", mig.version, mig.name)
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{mig.sql}\n;\n"
            f"PRAGMA user_version = {mig.version};\n"
            # name matches [a-z0-9_]+ and checksum is hex, so inlining is safe.
            "INSERT INTO schema_migrations (version, name, checksum) "
            f"VALUES ({mig.version}, '{mig.name}', '{mig.checksum}');\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise MigrationError(f"Falha na migração {mig.version:04d}_{mig.name}: {exc}") from exc

    return current, target


def _verify_applied(conn: sqlite3.Connection, applied: list[Migration]) -> None:
    rows = {r["version"]: r["checksum"] for r in conn.execute("SELECT version, checksum FROM schema_migrations")}
    for mig in applied:
        recorded = rows.get(mig.version)
        if recorded is not None and recorded != mig.checksum:
            raise MigrationError(
                f"A migração {mig.version:04d}_{mig.name} foi alterada depois de aplicada. "
                "Crie uma migração nova em vez de editar uma antiga."
            )


def _backup(conn: sqlite3.Connection, dest: Path) -> None:
    if dest.exists():
        return  # keep the first backup taken at this version
    log.info("Copiando o catálogo para %s antes de migrar", dest)
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
