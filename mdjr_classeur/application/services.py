from __future__ import annotations

import shutil
from pathlib import Path

from ..cache import ClassificationCache
from ..classifier import Classification, LocalClassifier, read_content, read_content_details
from ..domain.models import PlanItem
from ..domain.paths import resolve_folder_pair
from ..domain.planning import build_destination
from .document_identity import ContentIdentityService
from .naming import FilenameProposalService
from ..infrastructure.filesystem import is_ignored_file
from .agent import AgentLedger
from .agent_brain import DocumentAgentBrain
from .learning import LearningMemory


class ClassificationService:
    def __init__(self, classifier: LocalClassifier, cache: ClassificationCache | None = None):
        self.classifier = classifier
        self.cache = cache

    def classify(self, path: Path, content: str | None = None, extraction_status: str | None = None) -> Classification:
        if self.cache is None:
            return self.classifier.classify(path, content=content, extraction_status=extraction_status)
        cached = self.cache.get(path, self.classifier.rules_version) if content is None else None
        if cached is not None:
            return cached
        result = self.classifier.classify(path, content=content, extraction_status=extraction_status)
        self.cache.put(path, self.classifier.rules_version, result)
        return result


class ScanService:
    def __init__(self, classification: ClassificationService, naming=None, identity=None, ledger: AgentLedger | None = None, brain: DocumentAgentBrain | None = None, learning: LearningMemory | None = None):
        self.classification = classification
        self.naming = naming or FilenameProposalService()
        self.identity = identity or ContentIdentityService()
        self.ledger = ledger
        self.brain = brain or DocumentAgentBrain()
        self.learning = learning
        if self.ledger is not None:
            self.ledger.recover_interrupted()

    def analyze_path(self, path: Path, destination_dir: Path, existing: bool = True, *, same_folder: bool = False) -> PlanItem | None:
        if not path.is_file() or path.is_symlink() or is_ignored_file(path):
            return None
        try:
            relative = path.relative_to(destination_dir)
            if same_folder:
                if len(relative.parts) > 1:
                    return None
            else:
                return None
        except ValueError:
            pass
        if self.ledger is not None and not self.ledger.needs_processing(path):
            return None
        if self.ledger is not None:
            self.ledger.start(path)
        try:
            content, extraction_status = read_content_details(path)
            classification = self.classification.classify(path, content=content, extraction_status=extraction_status)
            if self.learning is not None and (classification.needs_review or classification.confidence < 80):
                learned = self.learning.learned_labels(filename=path.name, context=content[:12000])
                if learned:
                    classification.subject = learned.get("subject", classification.subject)
                    classification.category = learned.get("category", classification.category)
                    if learned.get("hierarchy"):
                        classification.hierarchy = tuple(part.strip() for part in learned["hierarchy"].split("/") if part.strip())
                    classification.reason += " Correction(s) humaine(s) similaire(s) réutilisée(s) localement."
                    classification.confidence = max(classification.confidence, 70)
            name_proposal = self.naming.propose(path, classification, content)
            identity = self.identity.identify(path, content)
            destination, target, reason = build_destination(destination_dir, classification, path.suffix, path.stem, name_stem=name_proposal.stem)
            item = PlanItem(
            path, classification, destination, target, existing=existing,
            destination_root=destination_dir, destination_reason=reason,
            suggested_name=name_proposal.stem, sha256=identity.sha256 if identity else "",
            normalized_text_sha256=identity.normalized_text_sha256 if identity else "",
            text_length=identity.text_length if identity else len(content),
                rename_reason=name_proposal.reason, rename_confidence=name_proposal.confidence,
            )
            decision = self.brain.decide(item)
            item.agent_action = decision.action.value
            item.agent_reason = decision.reason
            item.agent_requires_confirmation = decision.requires_confirmation
            if self.ledger is not None:
                self.ledger.finish(path, "done", target=item.destination_file)
            return item
        except Exception as exc:
            if self.ledger is not None:
                self.ledger.finish(path, "failed", str(exc))
            raise

    def iter_scan(self, source_dir: Path, destination_dir: Path):
        """Parcourt le dossier sans matérialiser tous les chemins ou résultats.

        L’ordre n’est volontairement pas trié : trier un million de chemins
        imposerait de les conserver en mémoire avant de commencer le travail.
        """
        source_dir, destination_dir = resolve_folder_pair(source_dir, destination_dir)
        same_folder = source_dir == destination_dir
        try:
            paths = source_dir.iterdir() if same_folder else source_dir.rglob("*")
            for path in paths:
                item = self.analyze_path(path, destination_dir, same_folder=same_folder)
                if item is not None:
                    yield item
        except OSError:
            return

    def scan_batches(self, source_dir: Path, destination_dir: Path, batch_size: int = 250):
        """Produit des lots bornés pour permettre une progression et une reprise."""
        batch: list[PlanItem] = []
        for item in self.iter_scan(source_dir, destination_dir):
            batch.append(item)
            if len(batch) >= max(1, int(batch_size)):
                yield batch
                batch = []
        if batch:
            yield batch

    def scan(self, source_dir: Path, destination_dir: Path) -> list[PlanItem]:
        """Compatibilité avec l’interface actuelle ; les nouveaux appels doivent utiliser scan_batches."""
        return [item for batch in self.scan_batches(source_dir, destination_dir) for item in batch]


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
