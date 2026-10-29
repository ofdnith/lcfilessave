from __future__ import annotations

import hashlib
import io
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acervo import auth, db
from acervo.app import create_app
from acervo.catalog import transaction
from acervo.config import Config

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(data_dir=tmp_path / "dados", workers=False, web_dir=tmp_path / "sem-web")


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "catalogo.db")
    db.migrate(c)
    yield c
    c.close()


class Api:
    """TestClient with a logged-in token and helpers for the common calls."""

    def __init__(self, client: TestClient, cfg: Config, token: str):
        self.client, self.cfg = client, cfg
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, url, **kw):
        return self.client.get(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def post(self, url, **kw):
        return self.client.post(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def upload(self, path: Path, *, name: str | None = None, source: str = "web", session_id=None,
               created_at=None, sha256=None, client_key=None) -> dict:
        params = {"source": source}
        for k, v in (("session_id", session_id), ("created_at", created_at), ("sha256", sha256),
                     ("client_key", client_key)):
            if v is not None:
                params[k] = str(v)
        res = self.post("/api/upload", params=params, content=path.read_bytes(),
                        headers={"X-Filename": name or path.name, "Content-Type": "application/octet-stream"})
        assert res.status_code == 200, res.text
        return res.json()

    def item(self, item_id: int) -> dict:
        return self.get(f"/api/items/{item_id}").json()

    def act(self, ids, action):
        res = self.post("/api/items/actions", json={"ids": ids, "action": action})
        assert res.status_code == 200, res.text
        return res.json()

    def run_jobs(self):
        from acervo.jobs import Worker
        from acervo.places import Gazetteer
        w = Worker(self.cfg, self.client.app.state.exiftool, Gazetteer(self.cfg.subdir("geo")))
        return w.run_pending()


def login(client: TestClient, cfg: Config, password: str = "senha-forte-123") -> str:
    c = db.connect(cfg.db_path)
    try:
        with transaction(c):
            auth.set_password(c, password)
            return auth.create_token(c, "api", "testes")
    finally:
        c.close()


@pytest.fixture
def api(cfg: Config):
    with TestClient(create_app(cfg)) as client:
        yield Api(client, cfg, login(client, cfg))


def make_jpeg(path: Path, *, color=(200, 30, 30), size=(320, 240), date: str | None = "2024:05:01 10:12:33",
              offset: str | None = "-03:00", gps: tuple[float, float] | None = None, text: str | None = None,
              pattern: int = 0) -> Path:
    im = Image.new("RGB", size, color)
    if pattern:  # photo-like content: random shapes, deterministic per `pattern`
        import random
        from PIL import ImageDraw
        rnd = random.Random(pattern)
        d = ImageDraw.Draw(im)
        for _ in range(25):
            x, y = rnd.randrange(size[0]), rnd.randrange(size[1])
            r = rnd.randrange(10, max(11, size[0] // 4))
            d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(rnd.randrange(256) for _ in range(3)))
    if text:
        from PIL import ImageDraw, ImageFont
        d = ImageDraw.Draw(im)
        try:
            font = ImageFont.load_default(size=40)
        except TypeError:
            font = ImageFont.load_default()
        d.text((20, 40), text, fill=(0, 0, 0), font=font)
    exif = Image.Exif()
    exif[271], exif[272] = "Apple", "iPhone 13"
    ifd = exif.get_ifd(0x8769)
    if date:
        ifd[36867] = date
    if offset:
        ifd[36881] = offset
    if gps:
        lat, lon = gps
        g = exif.get_ifd(0x8825)
        def dms(v):
            v = abs(v)
            d = int(v); m = int((v - d) * 60); s = round(((v - d) * 60 - m) * 60, 2)
            return (d, m, s)
        g[1], g[2], g[3], g[4] = ("S" if lat < 0 else "N"), dms(lat), ("W" if lon < 0 else "E"), dms(lon)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90, exif=exif.tobytes())
    path.write_bytes(buf.getvalue())
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def insert_item(conn: sqlite3.Connection, sha: str = SHA_A, **overrides) -> int:
    values = {
        "sha256": sha,
        "kind": "photo",
        "size_bytes": 1000,
        "captured_at": "2024-05-01T10:12:00",
        "date_source": "exif",
        "source": "mac",
        "original_name": "IMG_1234.HEIC",
    }
    values.update(overrides)
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO items ({cols}) VALUES ({marks})", tuple(values.values()))
    return cur.lastrowid


def insert_file(conn: sqlite3.Connection, item_id: int, sha: str = SHA_A, rel_path: str = "entrada/x.heic",
                role: str = "original") -> int:
    cur = conn.execute(
        "INSERT INTO files (item_id, role, sha256, size_bytes, ext, rel_path) VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, role, sha, 1000, "heic", rel_path),
    )
    return cur.lastrowid
