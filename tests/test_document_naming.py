from pathlib import Path

from mdjr_classeur.application.document_identity import ContentIdentityService
from mdjr_classeur.application.naming import FilenameProposalService
from mdjr_classeur.application.services import ClassificationService, ScanService
from mdjr_classeur.classifier import Classification, LocalClassifier
from mdjr_classeur.domain.models import PlanItem
from mdjr_classeur.infrastructure.filesystem import FileOperationService


def test_filename_proposal_uses_content_and_context(tmp_path: Path):
    source = tmp_path / "IMG_001.txt"
    content = "Cours de physique\nÉlectromagnétisme et champ électrique"
    source.write_text(content, encoding="utf-8")
    classification = LocalClassifier().classify(source)
    proposal = FilenameProposalService().propose(source, classification, content)
    assert proposal.stem != source.stem
    assert "Physique" in proposal.stem
    assert proposal.confidence > 50


def test_scan_item_carries_name_and_content_identity(tmp_path: Path):
    source_dir = tmp_path / "source"
    destination_dir = tmp_path / "destination"
    source_dir.mkdir()
    source = source_dir / "document.txt"
    source.write_text("Cours de physique sur le champ électrique", encoding="utf-8")
    service = ScanService(ClassificationService(LocalClassifier()))
    item = service.scan(source_dir, destination_dir)[0]
    assert item.suggested_name
    assert item.sha256
    assert item.destination_file.stem == item.suggested_name


def test_normalized_text_duplicate_is_not_copied(tmp_path: Path):
    source_dir = tmp_path / "source"
    destination_dir = tmp_path / "destination"
    source_dir.mkdir()
    destination_dir.mkdir()
    source = source_dir / "copie.txt"
    existing = destination_dir / "original.txt"
    source.write_text("Titre\nCours   de physique", encoding="utf-8")
    existing.write_text("titre\nCours de physique", encoding="utf-8")
    identity = ContentIdentityService().identify(source)
    classification = Classification("Physique", "Cours", 80, "test", title="Cours physique")
    item = PlanItem(source, classification, destination_dir, destination_dir / "Cours physique.txt", destination_root=destination_dir, sha256=identity.sha256, normalized_text_sha256=identity.normalized_text_sha256)
    results = FileOperationService().execute([item], "copy")
    assert results[0]["operation"] == "duplicate"
    assert results[0]["duplicate_kind"] == "texte normalisé identique"
    assert source.exists()
    assert not (destination_dir / "Cours physique.txt").exists()
