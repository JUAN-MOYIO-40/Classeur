from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..cache import ClassificationCache
from ..classifier import LocalClassifier
from ..dedupe import DuplicateReport, scan_duplicates
from ..domain.models import PlanItem
from ..application.services import ClassificationService, ScanService, UndoService
from ..application.indexing import SearchIndexService
from ..infrastructure.filesystem import FileOperationService, is_ignored_file
from ..search_index import SearchIndex


class ScanWorker(QThread):
    completed = Signal(object, int)
    failed = Signal(str)

    def __init__(self, source_dir: Path, destination_dir: Path, classifier: LocalClassifier | None = None, cache: ClassificationCache | None = None, service: ScanService | None = None):
        super().__init__()
        self.service = service or ScanService(ClassificationService(classifier, cache))
        self.source_dir = source_dir
        self.destination_dir = destination_dir

    def run(self):
        try:
            items = self.service.scan(self.source_dir, self.destination_dir)
            self.completed.emit(items, len(items))
        except Exception as exc:
            self.failed.emit(str(exc))


class ApplyWorker(QThread):
    completed = Signal(object)
    progress = Signal(int, str)
    failed = Signal(str)

    def __init__(self, items: list[PlanItem], mode: str, service: FileOperationService | None = None):
        super().__init__()
        self.items = items
        self.mode = mode
        self.service = service or FileOperationService()

    def run(self):
        try:
            results = self.service.execute(self.items, self.mode, progress=self.progress.emit)
            self.completed.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class SearchIndexWorker(QThread):
    completed = Signal(int)
    failed = Signal(str)

    def __init__(self, roots: list[Path], index: SearchIndex, classifier: LocalClassifier, cache: ClassificationCache, pending_items=None):
        super().__init__()
        self.roots = roots
        self.index = index
        self.classifier = classifier
        self.cache = cache
        self.service = SearchIndexService(index, classifier, cache)
        self.pending_items = pending_items or []

    def run(self):
        try:
            indexed = self.service.refresh(self.roots, self.pending_items)
            self.completed.emit(indexed)
        except Exception as exc:
            self.failed.emit(str(exc))


class DuplicateWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, roots: list[Path]):
        super().__init__()
        self.roots = roots

    def run(self):
        try:
            self.completed.emit(scan_duplicates(self.roots))
        except Exception as exc:
            self.failed.emit(str(exc))


