from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .classifier import Classification, fold
from .semantic import NativeSemanticEngine


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


@dataclass
class VersionGroup:
    name_stem: str
    versions: list[SearchRecord]

    @property
    def count(self) -> int:
        return len(self.versions)

    @property
    def latest(self) -> SearchRecord:
        return max(self.versions, key=lambda r: r.mtime_ns)


class SearchIndex:
    """Index de recherche local avec FTS5 + fallback sémantique n-gram, sans réseau."""

    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(database_path), check_same_thread=False, timeout=5.0)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self._fts_enabled = False
        self._semantic = NativeSemanticEngine()
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
                sha256 TEXT NOT NULL DEFAULT '',
                normalized_text_sha256 TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            )"""
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(documents)").fetchall()}
        if "hierarchy" not in columns:
            self.connection.execute("ALTER TABLE documents ADD COLUMN hierarchy TEXT NOT NULL DEFAULT ''")
        if "sha256" not in columns:
            self.connection.execute("ALTER TABLE documents ADD COLUMN sha256 TEXT NOT NULL DEFAULT ''")
        if "normalized_text_sha256" not in columns:
            self.connection.execute("ALTER TABLE documents ADD COLUMN normalized_text_sha256 TEXT NOT NULL DEFAULT ''")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_documents_mtime ON documents(mtime_ns)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_documents_text_sha256 ON documents(normalized_text_sha256)")
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

    def upsert(self, path: Path, classification: Classification, status: str = "classé", hierarchy: str = "", commit: bool = True, sha256: str = "", normalized_text_sha256: str = "") -> bool:
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
            sha256,
            normalized_text_sha256,
            time.time(),
        )
        existing = self.connection.execute("SELECT id FROM documents WHERE path = ?", (resolved,)).fetchone()
        if existing:
            document_id = existing[0]
            self.connection.execute(
                """UPDATE documents SET name=?, subject=?, category=?, hierarchy=?, title=?, preview=?, status=?,
                   size=?, mtime_ns=?, sha256=?, normalized_text_sha256=?, updated_at=? WHERE id=?""",
                values[1:] + (document_id,),
            )
            if self._fts_enabled:
                self.connection.execute("DELETE FROM documents_fts WHERE rowid = ?", (document_id,))
        else:
            cursor = self.connection.execute(
                """INSERT INTO documents(path, name, subject, category, hierarchy, title, preview, status, size, mtime_ns, sha256, normalized_text_sha256, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            document_id = cursor.lastrowid
        if self._fts_enabled:
            self.connection.execute(
                "INSERT INTO documents_fts(rowid, path, name, subject, category, hierarchy, title, preview, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                , (document_id, resolved, fold(path.name), fold(classification.subject), fold(classification.category), fold(hierarchy), fold(classification.title), fold(classification.extracted_preview), fold(status))
            )
        if commit:
            self.connection.commit()
        return True

    def upsert_plan_item(self, item, status: str = "en attente", commit: bool = True) -> bool:
        return self.upsert(
            item.source, item.classification, status, getattr(item, "hierarchy_label", ""),
            commit=commit,
            sha256=getattr(item, "sha256", ""),
            normalized_text_sha256=getattr(item, "normalized_text_sha256", ""),
        )

    def find_duplicate(self, sha256: str = "", normalized_text_sha256: str = "", exclude_path: Path | None = None) -> tuple[Path, str] | None:
        excluded = str(exclude_path.resolve()) if exclude_path else ""
        if sha256:
            row = self.connection.execute(
                "SELECT path FROM documents WHERE sha256 = ? AND path != ? LIMIT 1", (sha256, excluded)
            ).fetchone()
            if row:
                return Path(row[0]), "octets identiques"
        if normalized_text_sha256:
            row = self.connection.execute(
                "SELECT path FROM documents WHERE normalized_text_sha256 = ? AND path != ? LIMIT 1", (normalized_text_sha256, excluded)
            ).fetchone()
            if row:
                return Path(row[0]), "texte normalisé identique"
        return None

    def find_near_duplicates(self, sha256: str = "", normalized_text_sha256: str = "", exclude_path: Path | None = None) -> list[tuple[Path, str]]:
        excluded = str(exclude_path.resolve()) if exclude_path else ""
        results: list[tuple[Path, str]] = []
        if sha256:
            rows = self.connection.execute(
                "SELECT path FROM documents WHERE sha256 = ? AND path != ?", (sha256, excluded)
            ).fetchall()
            results.extend((Path(row[0]), "octets identiques") for row in rows)
        if normalized_text_sha256:
            rows = self.connection.execute(
                "SELECT path FROM documents WHERE normalized_text_sha256 = ? AND path != ?", (normalized_text_sha256, excluded)
            ).fetchall()
            existing = {str(r[0]) for r in results}
            results.extend((Path(row[0]), "texte normalisé identique") for row in rows if row[0] not in existing)
        return results

    def delete_path(self, path: Path):
        resolved = str(path.resolve())
        row = self.connection.execute("SELECT id FROM documents WHERE path = ?", (resolved,)).fetchone()
        if row:
            self.connection.execute("DELETE FROM documents WHERE id = ?", (row[0],))
            if self._fts_enabled:
                self.connection.execute("DELETE FROM documents_fts WHERE rowid = ?", (row[0],))
            self.connection.commit()

    def remove_missing(self, commit: bool = True):
        rows = self.connection.execute("SELECT id, path FROM documents").fetchall()
        missing = [row for row in rows if not Path(row[1]).exists()]
        for document_id, _path in missing:
            self.connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            if self._fts_enabled:
                self.connection.execute("DELETE FROM documents_fts WHERE rowid = ?", (document_id,))
        if missing and commit:
            self.connection.commit()

    @staticmethod
    def _query_tokens(query: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", fold(query))

    def search(self, query: str, status: str = "Tous", limit: int = 300) -> list[SearchRecord]:
        tokens = self._query_tokens(query)
        limit = max(1, min(int(limit), 2000))
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
                token_fields = " AND ".join(fields for _token in tokens)
                sql = (
                    "SELECT path, name, subject, category, hierarchy, title, preview, status, size, mtime_ns FROM documents WHERE "
                    + token_fields + where_status + " ORDER BY updated_at DESC LIMIT ?"
                )
                params = [f"%{token}%" for token in tokens for _field in range(7)]
            else:
                sql = "SELECT path, name, subject, category, hierarchy, title, preview, status, size, mtime_ns FROM documents WHERE 1=1" + where_status + " ORDER BY updated_at DESC LIMIT ?"
        if status != "Tous":
            params.append(status)
        params.append(limit)
        rows = self.connection.execute(sql, params).fetchall()
        return [SearchRecord(*row) for row in rows]

    def semantic_search(self, query: str, status: str = "Tous", limit: int = 50) -> list[tuple[SearchRecord, float]]:
        """Recherche sémantique locale : n-gram cosine sur les documents indexés."""
        all_rows = self.connection.execute(
            "SELECT path, name, subject, category, hierarchy, title, preview, status, size, mtime_ns FROM documents"
            + (" WHERE status = ?" if status != "Tous" else ""),
            (status,) if status != "Tous" else (),
        ).fetchall()
        if not all_rows or not query.strip():
            return []
        query_features = self._semantic._features(query)
        scored: list[tuple[float, SearchRecord]] = []
        for row in all_rows:
            record = SearchRecord(*row)
            doc_text = f"{record.name} {record.subject} {record.category} {record.hierarchy} {record.title} {record.preview}"
            doc_features = self._semantic._features(doc_text)
            score = self._semantic._cosine(query_features, doc_features)
            if score > 0.05:
                scored.append((score, record))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [(record, score) for score, record in scored[:limit]]

    def hybrid_search(self, query: str, status: str = "Tous", limit: int = 100) -> list[SearchRecord]:
        """FTS5 d'abord, puis complète avec la recherche sémantique si trop peu de résultats."""
        fts_results = self.search(query, status, limit)
        if len(fts_results) >= min(10, limit):
            return fts_results[:limit]
        semantic_results = self.semantic_search(query, status, limit=limit)
        seen = {r.path for r in fts_results}
        combined = list(fts_results)
        for record, _score in semantic_results:
            if record.path not in seen:
                combined.append(record)
                seen.add(record.path)
            if len(combined) >= limit:
                break
        return combined

    def find_versions(self, name_stem: str, limit: int = 50) -> list[SearchRecord]:
        """Trouve les versions d'un même document par nom normalisé similaire."""
        folded = fold(name_stem)
        if not folded:
            return []
        rows = self.connection.execute(
            "SELECT path, name, subject, category, hierarchy, title, preview, status, size, mtime_ns FROM documents ORDER BY updated_at DESC"
        ).fetchall()
        results = []
        for row in rows:
            record_name_folded = fold(Path(row[0]).stem)
            if not record_name_folded:
                continue
            tokens_query = set(folded.split())
            tokens_doc = set(record_name_folded.split())
            if not tokens_query:
                continue
            overlap = len(tokens_query & tokens_doc) / max(len(tokens_query), len(tokens_doc))
            if overlap >= 0.6:
                results.append(SearchRecord(*row))
            if len(results) >= limit:
                break
        return results

    def detect_version_groups(self, limit: int = 100) -> list[VersionGroup]:
        """Détecte les groupes de fichiers qui sont des versions du même document."""
        rows = self.connection.execute(
            "SELECT path, name, subject, category, hierarchy, title, preview, status, size, mtime_ns FROM documents ORDER BY name"
        ).fetchall()
        by_stem: dict[str, list[SearchRecord]] = {}
        for row in rows:
            record = SearchRecord(*row)
            stem = fold(Path(record.path).stem)
            stem_clean = re.sub(r"\s*\(\d+\)\s*$", "", stem).strip()
            stem_clean = re.sub(r"\s*v\d+\s*$", "", stem_clean).strip()
            stem_clean = re.sub(r"\s*-\s*copie\s*$", "", stem_clean).strip()
            stem_clean = re.sub(r"\s*copy\s*$", "", stem_clean).strip()
            if stem_clean:
                by_stem.setdefault(stem_clean, []).append(record)
        groups = []
        for stem, records in by_stem.items():
            if len(records) >= 2:
                records.sort(key=lambda r: r.mtime_ns, reverse=True)
                groups.append(VersionGroup(stem, records))
        groups.sort(key=lambda g: g.count, reverse=True)
        return groups[:limit]

    def stats(self) -> dict[str, int]:
        total = self.connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        classified = self.connection.execute("SELECT COUNT(*) FROM documents WHERE status = 'classé'").fetchone()[0]
        pending = self.connection.execute("SELECT COUNT(*) FROM documents WHERE status = 'en attente'").fetchone()[0]
        unique_subjects = self.connection.execute("SELECT COUNT(DISTINCT subject) FROM documents").fetchone()[0]
        unique_categories = self.connection.execute("SELECT COUNT(DISTINCT category) FROM documents").fetchone()[0]
        return {
            "total": total,
            "classified": classified,
            "pending": pending,
            "subjects": unique_subjects,
            "categories": unique_categories,
        }

    def close(self):
        self.connection.close()
