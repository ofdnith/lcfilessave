"""In-memory index of perceptual hashes, for near-duplicate grouping.

Scanning every photo of the catalog in SQL for each new thumbnail makes a big
first import quadratic (hours on the Snapdragon 680 at ~100k photos). Here the
hashes live in memory, loaded once from the catalog: with numpy (Termux:
`pkg install python-numpy`) a lookup over 100k photos takes about a millisecond;
without it, a plain Python loop is still several times faster than SQL.

The index never decides state: callers filter the ids it returns against the
catalog (trash, purged…), so it may safely hold stale entries.
"""

from __future__ import annotations

import sqlite3

try:
    import numpy as np
except ImportError:  # optional
    np = None  # type: ignore[assignment]

MASK = (1 << 64) - 1


class PhashIndex:
    def __init__(self, use_numpy: bool = True) -> None:
        self.use_numpy = use_numpy and np is not None
        self.loaded = False
        self._pos: dict[int, int] = {}
        self._ids: list[int] = []
        self._hashes: list[int] = []  # unsigned 64-bit
        self._np_ids = None
        self._np_hashes = None
        self._size = 0

    def __len__(self) -> int:
        return self._size

    def load(self, conn: sqlite3.Connection) -> None:
        for row in conn.execute("SELECT id, phash FROM items WHERE phash IS NOT NULL AND state <> 'purged'"):
            self.add(row[0], row[1])
        self.loaded = True

    def add(self, item_id: int, phash: int) -> None:
        value = phash & MASK
        pos = self._pos.get(item_id)
        if pos is not None:  # thumbnail regenerated: replace in place
            if self.use_numpy:
                self._np_hashes[pos] = value
            else:
                self._hashes[pos] = value
            return
        self._pos[item_id] = self._size
        if self.use_numpy:
            if self._np_ids is None or self._size == len(self._np_ids):
                self._grow()
            self._np_ids[self._size] = item_id
            self._np_hashes[self._size] = value
        else:
            self._ids.append(item_id)
            self._hashes.append(value)
        self._size += 1

    def _grow(self) -> None:
        capacity = max(1024, 2 * (len(self._np_ids) if self._np_ids is not None else 0))
        ids = np.zeros(capacity, dtype=np.int64)
        hashes = np.zeros(capacity, dtype=np.uint64)
        if self._np_ids is not None:
            ids[: self._size] = self._np_ids[: self._size]
            hashes[: self._size] = self._np_hashes[: self._size]
        self._np_ids, self._np_hashes = ids, hashes

    def near(self, phash: int, max_distance: int, exclude: int | None = None) -> list[int]:
        """Ids whose hash is within `max_distance` bits of `phash`."""
        value = phash & MASK
        if self.use_numpy:
            if not self._size:
                return []
            diff = self._np_hashes[: self._size] ^ np.uint64(value)
            hits = self._np_ids[: self._size][_popcount(diff) <= max_distance]
            return [int(i) for i in hits if i != exclude]
        return [i for i, h in zip(self._ids, self._hashes) if (h ^ value).bit_count() <= max_distance and i != exclude]


_BYTE_BITS = None


def _popcount(arr):
    if hasattr(np, "bitwise_count"):  # numpy >= 2.0
        return np.bitwise_count(arr)
    global _BYTE_BITS
    if _BYTE_BITS is None:
        _BYTE_BITS = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)
    return _BYTE_BITS[arr.view(np.uint8)].reshape(-1, 8).sum(axis=1)
