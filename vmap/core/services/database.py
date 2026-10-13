"""SQLite store for app settings and recent files.

Documents are never stored here - .vmap files stay portable.
API keys/secrets will NOT go here either (OS keychain, see SECURITY notes).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recent_files (path TEXT PRIMARY KEY, seq INTEGER NOT NULL);
"""


class AppDatabase:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: object) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    def add_recent(self, path: str | Path, limit: int = 12) -> None:
        p = str(Path(path).resolve())
        with self._conn:
            self._conn.execute(
                "INSERT INTO recent_files(path, seq) "
                "VALUES(?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM recent_files)) "
                "ON CONFLICT(path) DO UPDATE SET seq = excluded.seq", (p,))
            self._conn.execute(
                "DELETE FROM recent_files WHERE path NOT IN "
                "(SELECT path FROM recent_files ORDER BY seq DESC LIMIT ?)", (limit,))

    def remove_recent(self, path: str | Path) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM recent_files WHERE path = ?",
                               (str(Path(path).resolve()),))

    def recent_files(self, limit: int = 12) -> list[str]:
        rows = self._conn.execute(
            "SELECT path FROM recent_files ORDER BY seq DESC LIMIT ?", (limit,))
        return [r[0] for r in rows]

    def clear_recent(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM recent_files")

    def close(self) -> None:
        self._conn.close()
