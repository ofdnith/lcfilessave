"""Offline reverse geocoding: GPS -> "Cidade, Estado, País".

Uses the free GeoNames city list (cities with 1000+ inhabitants, ~10 MB),
downloaded once by `acervo baixar-cidades` into <dados>/geo/. Nothing is sent
to the internet when looking up a place.

Index: a dict of 1°×1° cells, so a lookup only checks the cities in the 3×3
cells around the point.
"""

from __future__ import annotations

import io
import logging
import math
import threading
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

CITIES_URL = "https://download.geonames.org/export/dump/cities1000.zip"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
COUNTRIES_URL = "https://download.geonames.org/export/dump/countryInfo.txt"
MAX_DISTANCE_KM = 40


def download(geo_dir: Path) -> None:
    geo_dir.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(CITIES_URL, timeout=120) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        (geo_dir / "cities.txt").write_bytes(zf.read("cities1000.txt"))
    for url, name in ((ADMIN1_URL, "admin1.txt"), (COUNTRIES_URL, "countries.txt")):
        with urllib.request.urlopen(url, timeout=120) as resp:
            (geo_dir / name).write_bytes(resp.read())


class Gazetteer:
    def __init__(self, geo_dir: Path) -> None:
        self.geo_dir = geo_dir
        self._cells: dict[tuple[int, int], list[tuple[float, float, str]]] | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return (self.geo_dir / "cities.txt").is_file()

    def _load(self) -> dict:
        with self._lock:
            if self._cells is not None:
                return self._cells
            admin1: dict[str, str] = {}
            p = self.geo_dir / "admin1.txt"
            if p.is_file():
                for line in p.read_text("utf-8").splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        admin1[parts[0]] = parts[1]
            countries: dict[str, str] = {}
            p = self.geo_dir / "countries.txt"
            if p.is_file():
                for line in p.read_text("utf-8").splitlines():
                    if line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) > 4:
                        countries[parts[0]] = parts[4]
            cells: dict[tuple[int, int], list[tuple[float, float, str]]] = {}
            with open(self.geo_dir / "cities.txt", encoding="utf-8") as fh:
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 11:
                        continue
                    try:
                        lat, lon = float(parts[4]), float(parts[5])
                    except ValueError:
                        continue
                    cc = parts[8]
                    state = admin1.get(f"{cc}.{parts[10]}")
                    label = ", ".join(x for x in (parts[1], state, countries.get(cc, cc)) if x)
                    cells.setdefault((math.floor(lat), math.floor(lon)), []).append((lat, lon, label))
            self._cells = cells
            return cells

    def lookup(self, lat: float, lon: float) -> str | None:
        if not self.available:
            return None
        cells = self._load()
        best, best_d = None, MAX_DISTANCE_KM
        cy, cx = math.floor(lat), math.floor(lon)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for clat, clon, label in cells.get((cy + dy, cx + dx), ()):
                    d = _km(lat, lon, clat, clon)
                    if d < best_d:
                        best, best_d = label, d
        return best


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))
