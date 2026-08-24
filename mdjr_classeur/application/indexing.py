from __future__ import annotations

from pathlib import Path

from ..cache import ClassificationCache
from ..classifier import LocalClassifier
from ..search_index import SearchIndex
from .services import ClassificationService
from ..infrastructure.filesystem import is_ignored_file


class SearchIndexService:
    """Reconstruit ou met à jour l’index sans dépendance à l’interface Qt."""

    def __init__(self, index: SearchIndex, classifier: LocalClassifier, cache: ClassificationCache):
        self.index = index
        self.classification = ClassificationService(classifier, cache)

    def refresh(self, roots: list[Path], pending_items=None) -> int:
        worker_index = SearchIndex(self.index.database_path)
        pending_items = pending_items or []
        indexed = 0
        try:
            worker_index.connection.execute("BEGIN")
            for root in roots:
                if not root.exists() or not root.is_dir():
                    continue
                for path in root.rglob("*"):
                    if not path.is_file() or path.is_symlink() or is_ignored_file(path):
                        continue
                    if not worker_index.needs_update(path, "classé"):
                        continue
                    classification = self.classification.classify(path)
                    worker_index.upsert(path, classification, "classé", " / ".join(classification.hierarchy), commit=False)
                    indexed += 1
            for item in pending_items:
                worker_index.upsert_plan_item(item, "en attente", commit=False)
                indexed += 1
            worker_index.remove_missing(commit=False)
            worker_index.connection.commit()
            return indexed
        except Exception:
            worker_index.connection.rollback()
            raise
        finally:
            worker_index.close()
