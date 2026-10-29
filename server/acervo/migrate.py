"""`acervo migrar` — copy a whole Acervo from the old server to this one.

Run on the NEW machine, with its own server stopped. The old server keeps
running, frozen read-only, and never deletes anything:

  1. tell the old server to freeze (POST /api/migration/start)
  2. download a consistent copy of its catalog
  3. download every file in its manifest (originals, thumbnails, medium
     previews, certificates, city list) to <file>.part, fsync, check the
     SHA-256 (originals against the catalog), rename
  4. adjust the catalog to this machine (microSD paths become local paths)
  5. confirm every original is present with the right size, write MIGRACAO.txt

Interrupted? Run the same command again: files already verified are skipped.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from . import db
from .catalog import now_iso
from .config import Config
from .storage import ensure_layout, fsync_dir

STATE_FILE = ".migracao.json"
CHUNK = 1024 * 1024


class MigrationError(RuntimeError):
    """Message in Portuguese, shown to the owner."""


# --- talking to the old server ------------------------------------------------------------

class Source:
    """HTTP access to the old server. `client` (httpx-like) is for tests."""

    def __init__(self, base_url: str, token: str, ca_file: Path | None = None, client=None) -> None:
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.client = client
        self.ctx = None
        if client is None and self.base.startswith("https://"):
            self.ctx = ssl.create_default_context(cafile=str(ca_file)) if ca_file else ssl.create_default_context()

    def _url(self, path: str, params: dict | None) -> str:
        return self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")

    def json(self, method: str, path: str, params: dict | None = None) -> dict:
        if self.client is not None:
            res = self.client.request(method, path, params=params, headers=self.headers)
            if res.status_code >= 400:
                raise MigrationError(f"{path}: {res.status_code} {res.text[:200]}")
            return res.json()
        req = urllib.request.Request(self._url(path, params), method=method, headers=self.headers,
                                     data=b"" if method == "POST" else None)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            if exc.code == 401:
                raise MigrationError("O servidor antigo recusou o token. Crie outro: acervo-ctl token migracao") from None
            raise MigrationError(f"{path}: {exc.code} {detail}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise MigrationError(f"Não consegui falar com {self.base}: {getattr(exc, 'reason', exc)}") from None

    def stream(self, path: str, params: dict | None = None) -> tuple[dict, Iterator[bytes]]:
        if self.client is not None:
            res = self.client.get(path, params=params, headers=self.headers)
            if res.status_code >= 400:
                raise MigrationError(f"{path}: {res.status_code}")
            return {k.lower(): v for k, v in res.headers.items()}, iter([res.content])
        req = urllib.request.Request(self._url(path, params), headers=self.headers)
        try:
            resp = urllib.request.urlopen(req, context=self.ctx, timeout=300)
        except urllib.error.HTTPError as exc:
            raise MigrationError(f"{path}: {exc.code}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise MigrationError(f"Não consegui falar com {self.base}: {getattr(exc, 'reason', exc)}") from None
        headers = {k.lower(): v for k, v in resp.headers.items()}

        def chunks():
            with resp:
                while block := resp.read(CHUNK):
                    yield block
        return headers, chunks()


def fetch_ca(base_url: str) -> tuple[bytes, str]:
    """Download the old server's CA certificate (trust on first use) and its fingerprint."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(base_url.rstrip("/") + "/ca.crt", context=ctx, timeout=30) as resp:
        pem = resp.read()
    return pem, ca_fingerprint(pem)


def ca_fingerprint(pem: bytes) -> str:
    der = ssl.PEM_cert_to_DER_cert(pem.decode())
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, 16, 2)) + "…"


# --- the migration ----------------------------------------------------------------------------

@dataclass
class Report:
    originals: int = 0
    aux: int = 0
    skipped: int = 0
    bytes: int = 0
    failed: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=now_iso)


def _download(source: Source, entry: dict, dest: Path, report: Report) -> None:
    if entry["kind"] == "original" and dest.exists() and dest.stat().st_size == entry["size"]:
        if _sha256(dest) == entry["sha256"]:
            report.skipped += 1
            return
    params = {"kind": entry["kind"], "path": entry["path"], "root": entry["root"]}
    last_error = "?"
    for attempt in range(3):
        try:
            headers, chunks = source.stream("/api/migration/file", params)
            expected = entry["sha256"] or headers.get("x-acervo-sha256")
            if entry["kind"] == "aux" and dest.exists() and expected and _sha256(dest) == expected:
                report.skipped += 1
                return
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            h = hashlib.sha256()
            with open(part, "wb") as fh:
                for block in chunks:
                    fh.write(block)
                    h.update(block)
                fh.flush()
                os.fsync(fh.fileno())
            if expected and h.hexdigest() != expected:
                part.unlink(missing_ok=True)
                raise MigrationError("hash não confere")
            os.replace(part, dest)
            fsync_dir(dest.parent)
            if entry["kind"] == "aux" and dest.parent.name == "certificados" and dest.suffix in (".key", ".pem"):
                os.chmod(dest, 0o600)
            report.bytes += entry["size"]
            if entry["kind"] == "original":
                report.originals += 1
            else:
                report.aux += 1
            return
        except (MigrationError, OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
            time.sleep(min(2 ** attempt, 10))
    report.failed.append(f"{entry['path']}: {last_error}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(CHUNK):
            h.update(block)
    return h.hexdigest()


def run(cfg: Config, source: Source, progress: Callable[[str], None] = print) -> Report:
    ensure_layout(cfg)
    state_path = cfg.data_dir / STATE_FILE
    if cfg.db_path.exists() and not state_path.exists():
        conn = db.connect(cfg.db_path)
        try:
            has_items = conn.execute("SELECT count(*) FROM items").fetchone()[0] if \
                conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'items'").fetchone() else 0
        finally:
            conn.close()
        if has_items:
            raise MigrationError(f"Esta máquina já tem um acervo com {has_items} itens em {cfg.data_dir}. "
                                 "Use uma pasta de dados vazia para receber a migração.")
    state_path.write_text(json.dumps({"from": source.base, "started_at": now_iso()}))

    progress("Congelando o servidor antigo (fica só para consulta)…")
    source.json("POST", "/api/migration/start")

    progress("Copiando o catálogo…")
    headers, chunks = source.stream("/api/migration/catalog")
    incoming = cfg.data_dir / "catalogo.db.migrando"
    with open(incoming, "wb") as fh:
        for block in chunks:
            fh.write(block)
        fh.flush()
        os.fsync(fh.fileno())
    if headers.get("x-acervo-sha256") and _sha256(incoming) != headers["x-acervo-sha256"]:
        raise MigrationError("O catálogo chegou corrompido; rode de novo.")
    check = sqlite3.connect(incoming)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise MigrationError("O catálogo copiado não passou na verificação de integridade.")
    finally:
        check.close()
    for suffix in ("-wal", "-shm"):
        Path(str(cfg.db_path) + suffix).unlink(missing_ok=True)
    os.replace(incoming, cfg.db_path)

    manifest = source.json("GET", "/api/migration/manifest")
    files = manifest["files"]
    free = shutil.disk_usage(cfg.data_dir).free
    if manifest["total_bytes"] > free:
        raise MigrationError(f"Espaço insuficiente: precisa de {manifest['total_bytes'] / 1e9:.1f} GB, "
                             f"há {free / 1e9:.1f} GB livres.")
    progress(f"Copiando {len(files)} arquivos ({manifest['total_bytes'] / 1e9:.1f} GB), conferindo cada hash…")
    report = Report()
    for n, entry in enumerate(files, 1):
        if ".." in Path(entry["path"]).parts or entry["path"].startswith("/"):
            report.failed.append(f"{entry['path']}: caminho inválido")
            continue
        _download(source, entry, cfg.data_dir / entry["path"], report)
        if n % 500 == 0 or n == len(files):
            progress(f"  {n}/{len(files)} · {report.bytes / 1e9:.2f} GB · {len(report.failed)} com erro")

    progress("Ajustando o catálogo para esta máquina…")
    conn = db.connect(cfg.db_path)
    try:
        db.migrate(conn, backup_dir=cfg.data_dir)
        conn.execute("UPDATE files SET root = 'main' WHERE root = 'sd'")
        conn.execute("DELETE FROM settings WHERE key IN ('migration_active', 'daily_session')")
        conn.execute("UPDATE uploads SET status = 'cancelled' WHERE status IN ('receiving', 'processing')")
        conn.execute("INSERT INTO events (actor, action, details) VALUES ('migration', 'migration-received', ?)",
                     (json.dumps({"from": source.base, "originals": report.originals + report.skipped}),),)
        missing = [r[0] for r in conn.execute("SELECT rel_path, size_bytes FROM files WHERE rel_path IS NOT NULL")
                   if not (cfg.data_dir / r[0]).is_file() or (cfg.data_dir / r[0]).stat().st_size != r[1]]
    finally:
        conn.close()
    report.failed += [f"{m}: ausente depois da cópia" for m in missing if not any(m in f for f in report.failed)]

    lines = [
        "Migração do Acervo",
        f"De: {source.base}",
        f"Início: {report.started_at} · Fim: {now_iso()}",
        f"Originais copiados e conferidos por SHA-256: {report.originals} (+{report.skipped} já estavam aqui)",
        f"Miniaturas, prévias, certificados e cidades: {report.aux}",
        f"Total copiado: {report.bytes / 1e9:.2f} GB",
        f"Problemas: {len(report.failed)}",
        *report.failed[:200],
    ]
    (cfg.data_dir / "MIGRACAO.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not report.failed:
        state_path.unlink(missing_ok=True)
    return report


def cancel(source: Source) -> None:
    source.json("POST", "/api/migration/cancel")
