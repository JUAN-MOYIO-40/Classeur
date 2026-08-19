from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .classifier import Classification, fold


@dataclass
class SearchRecord:
    path: str
    name: str
    subject: str
    category: str
    hierarchy: str
    title: str
    preview: str
    status: str
    size: int
    mtime_ns: int


class SearchIndex:
    """Index de recherche local, rapide et indépendant de toute connexion Internet."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(database_path), check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._fts_enabled = False
        self._initialize()

    def _initialize(self):
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                subject TEXT NOT NULL,
                category TEXT NOT NULL,
                hierarchy TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                preview TEXT NOT NULL,
                status TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(documents)").fetchall()}
        if "hierarchy" not in columns:
            self.connection.execute("ALTER TABLE documents ADD COLUMN hierarchy TEXT NOT NULL DEFAULT ''")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)")
        try:
            fts_columns = {row[1] for row in self.connection.execute("PRAGMA table_info(documents_fts)").fetchall()}
            if fts_columns and "hierarchy" not in fts_columns:
                self.connection.execute("DROP TABLE documents_fts")
            self.connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(path, name, subject, category, hierarchy, title, preview, status)"
            )
            self._fts_enabled = True
        except sqlite3.OperationalError:
            self._fts_enabled = False
        self.connection.commit()

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return stat.st_size, stat.st_mtime_ns
        except OSError:
            return None

    def needs_update(self, path: Path, status: str) -> bool:
        signature = self._file_signature(path)
        if signature is None:
            return False
        row = self.connection.execute(
            "SELECT size, mtime_ns, status FROM documents WHERE path = ?", (str(path.resolve()),)
        ).fetchone()
        return row is None or tuple(row) != (signature[0], signature[1], status)

    def upsert(self, path: Path, classification: Classification, status: str = "classé", hierarchy: str = "") -> bool:
        hierarchy = hierarchy or " / ".join(classification.hierarchy)
        signature = self._file_signature(path)
        if signature is None:
            return False
        resolved = str(path.resolve())
        values = (
            resolved,
            path.name,
            classification.subject,
            classification.category,
            hierarchy,
            classification.title,
            classification.extracted_preview,
            status,
            signature[0],
            signature[1],
            time.time(),
        )
        existing = self.connection.execute("SELECT id FROM documents WHERE path = ?", (resolved,)).fetchone()
        if existing:
            document_id = existing[0]
            self.connection.execute(
                """UPDATE documents SET name=?, subject=?, category=?, hierarchy=?, title=?, preview=?, status=?,
                   size=?, mtime_ns=?, updated_at=? WHERE id=?""",
                values[1:] + (document_id,),
            )
            if self._fts_enabled:
                self.connection.execute("DELETE FROM documents_fts WHERE rowid = ?", (document_id,))
        else:
            cursor = self.connection.execute(
                """INSERT INTO documents(path, name, subject, category, hierarchy, title, preview, status, size, mtime_ns, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            document_id = cursor.lastrowid
        if self._fts_enabled:
            self.connection.execute(
                "INSERT INTO documents_fts(rowid, path, name, subject, category, hierarchy, title, preview, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                , (document_id, resolved, fold(path.name), fold(classification.subject), fold(classification.category), fold(hierarchy), fold(classification.title), fold(classification.extracted_preview), fold(status))
            )
        self.connection.commit()
        return True

    def upsert_plan_item(self, item, status: str = "en attente") -> bool:
        return self.upsert(item.source, item.classification, status, getattr(item, "hierarchy_label", ""))

    def delete_path(self, path: Path):
        resolved = str(path.resolve())
        row = self.connection.execute("SELECT id FROM documents WHERE path = ?", (resolved,)).fetchone()
        if row:
            self.connection.execute("DELETE FROM documents WHERE id = ?", (row[0],))
            if self._fts_enabled:
                self.connection.execute("DELETE FROM documents_fts WHERE rowid = ?", (row[0],))
            self.connection.commit()

    def remove_missing(self):
        rows = self.connection.execute("SELECT id, path FROM documents").fetchall()
        missing = [row for row in rows if not Path(row[1]).exists()]
        for document_id, _path in missing:
            self.connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            if self._fts_enabled:
                self.connection.execute("DELETE FROM documents_fts WHERE rowid = ?", (document_id,))
        if missing:
            self.connection.commit()

    @staticmethod
    def _query_tokens(query: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", fold(query))

    def search(self, query: str, status: str = "Tous", limit: int = 300) -> list[SearchRecord]:
        tokens = self._query_tokens(query)
        where_status = "" if status == "Tous" else " AND documents.status = ?"
        params: list[object] = []
        if self._fts_enabled and tokens:
            match = " AND ".join(f"{token}*" for token in tokens)
            sql = (
                "SELECT documents.path, documents.name, documents.subject, documents.category, documents.hierarchy, documents.title, "
                "documents.preview, documents.status, documents.size, documents.mtime_ns "
                "FROM documents JOIN documents_fts ON documents_fts.rowid = documents.id "
                "WHERE documents_fts MATCH ?" + where_status + " ORDER BY rank LIMIT ?"
            )
            params = [match]
        else:
            fields = "(LOWER(path) LIKE ? OR LOWER(name) LIKE ? OR LOWER(subject) LIKE ? OR LOWER(category) LIKE ? OR LOWER(hierarchy) LIKE ? OR LOWER(title) LIKE ? OR LOWER(preview) LIKE ?)"
            if tokens:
                value = f"%{' '.join(tokens)}%"
                sql = (
                    "SELECT path, name, subject, category, hierarchy, title, preview, status, size, mtime_ns FROM documents WHERE "
                    + fields + where_status + " ORDER BY updated_at DESC LIMIT ?"
                )
                params = [value] * 7
            else:
                sql = "SELECT path, name, subject, category, hierarchy, title, preview, status, size, mtime_ns FROM documents WHERE 1=1" + where_status + " ORDER BY updated_at DESC LIMIT ?"
        if status != "Tous":
            params.append(status)
        params.append(limit)
        rows = self.connection.execute(sql, params).fetchall()
        return [SearchRecord(*row) for row in rows]

    def close(self):
        self.connection.close()
