from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CorrectionExample:
    path: str
    fingerprint: str
    text_signature: str
    subject: str
    category: str
    hierarchy: str
    suggested_name: str
    tokens: tuple[str, ...]
    created_at: float


class LearningMemory:
    """Mémoire locale des corrections validées par l’utilisateur.

    Chaque correction devient un exemple supervisé. Les exemples sont conservés
    localement et ne sont jamais envoyés à un service distant par cette classe.
    """

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.database_path), timeout=10.0)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS correction_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                fingerprint TEXT NOT NULL DEFAULT '',
                text_signature TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL,
                category TEXT NOT NULL,
                hierarchy TEXT NOT NULL DEFAULT '',
                suggested_name TEXT NOT NULL DEFAULT '',
                tokens TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_corrections_subject ON correction_examples(subject)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_corrections_category ON correction_examples(category)")
        self.connection.commit()

    @staticmethod
    def tokenize(text: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(re.findall(r"[a-z0-9]{3,}", text.casefold())))

    def record(self, *, path: Path, fingerprint: str, text_signature: str, subject: str, category: str, hierarchy: str = "", suggested_name: str = "", context: str = "") -> None:
        tokens = self.tokenize(f"{path.name} {context} {subject} {category} {hierarchy}")
        self.connection.execute(
            """INSERT INTO correction_examples
               (path, fingerprint, text_signature, subject, category, hierarchy, suggested_name, tokens, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(path.resolve()), fingerprint, text_signature, subject.strip(), category.strip(), hierarchy.strip(), suggested_name.strip(), json.dumps(tokens), time.time()),
        )
        self.connection.commit()

    def suggest(self, *, filename: str, context: str = "", limit: int = 5) -> list[CorrectionExample]:
        query_tokens = set(self.tokenize(f"{filename} {context}"))
        if not query_tokens:
            return []
        rows = self.connection.execute(
            "SELECT path, fingerprint, text_signature, subject, category, hierarchy, suggested_name, tokens, created_at FROM correction_examples ORDER BY created_at DESC"
        ).fetchall()
        scored: list[tuple[float, CorrectionExample]] = []
        for row in rows:
            tokens = tuple(json.loads(row[7]))
            overlap = len(query_tokens & set(tokens))
            if overlap == 0:
                continue
            score = overlap / max(1, len(query_tokens | set(tokens)))
            scored.append((score, CorrectionExample(*row[:7], tokens, row[8])))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [example for _score, example in scored[: max(1, int(limit))]]

    def learned_labels(self, *, filename: str, context: str = "") -> dict[str, str]:
        suggestions = self.suggest(filename=filename, context=context, limit=5)
        if not suggestions:
            return {}
        def majority(values: list[str]) -> str:
            return max(set(values), key=values.count)
        return {
            "subject": majority([item.subject for item in suggestions]),
            "category": majority([item.category for item in suggestions]),
            "hierarchy": majority([item.hierarchy for item in suggestions if item.hierarchy] or [suggestions[0].hierarchy]),
        }

    def close(self) -> None:
        self.connection.close()
