from pathlib import Path

from mdjr_classeur.application.naming import FilenameProposalService
from mdjr_classeur.classifier import Classification


def test_birth_date_is_not_used_as_document_title(tmp_path: Path):
    classification = Classification(
        subject="Administratif",
        category="Administratif",
        confidence=48,
        reason="signaux faibles",
        title="Date de naissance : 12/03/2001",
        extracted_preview="Date de naissance : 12/03/2001\nNom : Jean Dupont\nAttestation de scolarité",
        needs_review=True,
    )
    proposal = FilenameProposalService().propose(
        tmp_path / "scan_001.pdf", classification, classification.extracted_preview
    )
    assert "naissance" not in proposal.stem.casefold()
    assert "12" not in proposal.stem


def test_birth_year_is_not_document_year():
    from mdjr_classeur.classifier import LocalClassifier

    assert LocalClassifier._year_from("Date de naissance : 12/03/2001") == ""
    assert LocalClassifier._year_from("Année universitaire 2024-2025") == "2024-2025"


def test_pure_date_is_not_used_as_fallback_title(tmp_path: Path):
    classification = Classification(
        subject="Administratif",
        category="Administratif",
        confidence=40,
        reason="scan",
        title="",
        extracted_preview="12/03/2001\nNom : Jean Dupont",
        needs_review=True,
    )
    proposal = FilenameProposalService().propose(
        tmp_path / "scan_002.pdf", classification, classification.extracted_preview
    )
    assert proposal.stem.casefold() != "12 03 2001"
