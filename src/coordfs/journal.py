"""The journal: an append-only record of every committed write.

Each entry stores, per file, the hash before the write and the hash after it.
A correct history forms an unbroken chain per path: the "before" of every
entry equals the "after" of the previous one. A gap means somebody wrote
outside the protocol, and exactly one change was lost.

SQLite is used for the atomicity of a single transaction, not as a database
in any interesting sense.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id      TEXT NOT NULL,
    path        TEXT NOT NULL,
    before_hash TEXT,
    after_hash  TEXT NOT NULL,
    written_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_path ON entries(path, id);
"""


def hash_file(path: Path) -> str | None:
    """SHA-256 of a file, or None if it does not exist."""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Entry:
    txn_id: str
    path: str
    before_hash: str | None
    after_hash: str
    written_at: float


class Journal:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def record(self, txn_id: str, changes: dict[str, tuple[str | None, str]]) -> None:
        """Append one entry per changed path, in a single SQLite transaction."""
        now = time.time()
        rows = [
            (txn_id, path, before, after, now)
            for path, (before, after) in changes.items()
        ]
        with self._connect() as con:
            con.executemany(
                "INSERT INTO entries (txn_id, path, before_hash, after_hash, written_at)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def entries_for(self, path: str) -> list[Entry]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT txn_id, path, before_hash, after_hash, written_at"
                " FROM entries WHERE path = ? ORDER BY id",
                (path,),
            ).fetchall()
        return [Entry(*r) for r in rows]

    def paths(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute("SELECT DISTINCT path FROM entries ORDER BY path").fetchall()
        return [r[0] for r in rows]
