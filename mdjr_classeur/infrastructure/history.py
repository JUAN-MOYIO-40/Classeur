from __future__ import annotations

import json
import time
from pathlib import Path

from .filesystem import atomic_write_text


class HistoryRepository:
    def __init__(self, path: Path, max_entries: int = 5000):
        self.path = path
        self.max_entries = max_entries

    def load(self) -> list[dict]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def append(self, entries: list[dict]) -> None:
        if not entries:
            return
        history = self.load()
        history.extend(entries)
        atomic_write_text(self.path, json.dumps(history[-self.max_entries:], ensure_ascii=False, indent=2))

    def remove_entries(self, entries: list[dict]) -> None:
        if not entries:
            return
        history = self.load()
        remaining = [entry for entry in history if entry not in entries]
        atomic_write_text(self.path, json.dumps(remaining, ensure_ascii=False, indent=2))
