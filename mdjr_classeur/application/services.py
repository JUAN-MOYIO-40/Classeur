from __future__ import annotations

import shutil
from pathlib import Path

from ..cache import ClassificationCache
from ..classifier import Classification, LocalClassifier
from ..domain.models import PlanItem
from ..domain.planning import build_destination
from ..infrastructure.filesystem import is_ignored_file


class ClassificationService:
    def __init__(self, classifier: LocalClassifier, cache: ClassificationCache | None = None):
        self.classifier = classifier
        self.cache = cache

    def classify(self, path: Path) -> Classification:
        if self.cache is None:
            return self.classifier.classify(path)
        cached = self.cache.get(path, self.classifier.rules_version)
        if cached is not None:
            return cached
        result = self.classifier.classify(path)
        self.cache.put(path, self.classifier.rules_version, result)
        return result


class ScanService:
    def __init__(self, classification: ClassificationService):
        self.classification = classification

    def scan(self, source_dir: Path, destination_dir: Path) -> list[PlanItem]:
        if not source_dir.exists() or not source_dir.is_dir():
            raise FileNotFoundError("Le dossier surveillé n’existe pas.")
        items: list[PlanItem] = []
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file() or path.is_symlink() or is_ignored_file(path):
                continue
            try:
                path.relative_to(destination_dir)
                continue
            except ValueError:
                pass
            classification = self.classification.classify(path)
            destination, target, reason = build_destination(destination_dir, classification, path.suffix, path.stem)
            items.append(PlanItem(path, classification, destination, target, existing=True, destination_root=destination_dir, destination_reason=reason))
        return items


class UndoService:
    """Restaure une dernière session uniquement si les cibles sont restées intactes."""

    def __init__(self, history):
        self.history = history

    @staticmethod
    def _record_matches_target(record: dict, target: Path) -> bool:
        try:
            stat = target.stat()
            expected_size = record.get("target_size")
            expected_mtime = record.get("target_mtime_ns")
            return (expected_size is None or stat.st_size == expected_size) and (expected_mtime is None or stat.st_mtime_ns == expected_mtime)
        except OSError:
            return False

    def undo_latest(self) -> tuple[int, list[str]]:
        entries = self.history.load()
        if not entries:
            return 0, []
        last = entries[-1]
        batch_id = last.get("batch_id")
        if batch_id:
            batch = [entry for entry in entries if isinstance(entry, dict) and entry.get("batch_id") == batch_id]
        else:
            batch = [last]
        undone: list[dict] = []
        skipped: list[str] = []
        for record in reversed(batch):
            target = Path(record.get("target", ""))
            source = Path(record.get("source", ""))
            if not target.exists() or not self._record_matches_target(record, target):
                skipped.append(target.name or str(target))
                continue
            try:
                if record.get("operation") == "move":
                    source.parent.mkdir(parents=True, exist_ok=True)
                    restored = source if not source.exists() else source.with_name(f"{source.stem} (restauré){source.suffix}")
                    shutil.move(str(target), str(restored))
                else:
                    target.unlink()
                undone.append(record)
            except OSError:
                skipped.append(target.name or str(target))
        if undone:
            self.history.remove_entries(undone)
        return len(undone), skipped
