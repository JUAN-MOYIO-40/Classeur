from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from .classifier import Classification


class ClassificationCache:
    """Cache local léger, indexé par chemin, taille, date de modification et version des règles."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=1.5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self):
        try:
            with self._connect() as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS classifications (
                        path TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        mtime_ns INTEGER NOT NULL,
                        rules_version TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        PRIMARY KEY (path, size, mtime_ns, rules_version)
                    )"""
                )
                connection.execute("CREATE INDEX IF NOT EXISTS idx_classifications_path ON classifications(path)")
        except sqlite3.Error:
            pass

    @staticmethod
    def signature(path: Path) -> tuple[str, int, int] | None:
        try:
            stat = path.stat()
            return str(path.resolve()), stat.st_size, stat.st_mtime_ns
        except OSError:
            return None

    def get(self, path: Path, rules_version: str) -> Classification | None:
        signature = self.signature(path)
        if signature is None:
            return None
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM classifications WHERE path=? AND size=? AND mtime_ns=? AND rules_version=?",
                    (*signature, rules_version),
                ).fetchone()
            if not row:
                return None
            return Classification(**json.loads(row[0]))
        except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
            return None

    def put(self, path: Path, rules_version: str, classification: Classification) -> None:
        signature = self.signature(path)
        if signature is None:
            return
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO classifications(path, size, mtime_ns, rules_version, payload) VALUES (?, ?, ?, ?, ?)",
                    (*signature, rules_version, json.dumps(asdict(classification), ensure_ascii=False)),
                )
        except (OSError, sqlite3.Error):
            pass

    def prune(self, max_rows: int = 10000) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM classifications WHERE rowid NOT IN (SELECT rowid FROM classifications ORDER BY rowid DESC LIMIT ?)",
                    (max_rows,),
                )
        except (OSError, sqlite3.Error):
            pass
