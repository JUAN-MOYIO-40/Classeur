from __future__ import annotations

import shutil
from pathlib import Path

from ..cache import ClassificationCache
from ..classifier import Classification, LocalClassifier, read_content
from ..domain.models import PlanItem
from ..domain.paths import resolve_folder_pair
from ..domain.planning import build_destination
from .document_identity import ContentIdentityService
from .naming import FilenameProposalService
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
    def __init__(self, classification: ClassificationService, naming=None, identity=None):
        self.classification = classification
        self.naming = naming or FilenameProposalService()
        self.identity = identity or ContentIdentityService()

    def analyze_path(self, path: Path, destination_dir: Path, existing: bool = True) -> PlanItem | None:
        if not path.is_file() or path.is_symlink() or is_ignored_file(path):
            return None
        try:
            path.relative_to(destination_dir)
            return None
        except ValueError:
            pass
        classification = self.classification.classify(path)
        content = read_content(path)
        name_proposal = self.naming.propose(path, classification, content)
        identity = self.identity.identify(path, content)
        destination, target, reason = build_destination(destination_dir, classification, path.suffix, path.stem, name_stem=name_proposal.stem)
        return PlanItem(
            path, classification, destination, target, existing=existing,
            destination_root=destination_dir, destination_reason=reason,
            suggested_name=name_proposal.stem, sha256=identity.sha256 if identity else "",
            normalized_text_sha256=identity.normalized_text_sha256 if identity else "",
            text_length=identity.text_length if identity else len(content),
            rename_reason=name_proposal.reason, rename_confidence=name_proposal.confidence,
        )

    def scan(self, source_dir: Path, destination_dir: Path) -> list[PlanItem]:
        source_dir, destination_dir = resolve_folder_pair(source_dir, destination_dir)
        items: list[PlanItem] = []
        for path in sorted(source_dir.rglob("*")):
            item = self.analyze_path(path, destination_dir)
            if item is not None:
                items.append(item)
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
