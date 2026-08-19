from pathlib import Path

from mdjr_classeur.classifier import LocalClassifier


def test_personal_finance_profile_is_hierarchical(tmp_path: Path):
    source = tmp_path / "2025_budget_familial_assurance_finance.pdf"
    source.write_text("2025\nBudget familial et assurance : dépenses, finance et épargne", encoding="utf-8")
    classification = LocalClassifier().classify(source)
    assert classification.year == "2025"
    assert classification.domain == "Économie et gestion"
    assert classification.subject == "Finance"
    assert classification.hierarchy[:3] == ("2025", "Économie et gestion", "Finance")


def test_professional_project_profile_is_hierarchical(tmp_path: Path):
    source = tmp_path / "2025_entreprise_projet_marketing_rapport.txt"
    source.write_text("2025\nRapport de projet marketing pour l'entreprise", encoding="utf-8")
    classification = LocalClassifier().classify(source)
    assert classification.year == "2025"
    assert classification.domain == "Économie et gestion"
    assert classification.category == "Projet"
    assert "Marketing" in classification.hierarchy or classification.subject == "Marketing"


def test_ambiguous_document_is_flagged_for_review(tmp_path: Path):
    source = tmp_path / "document_notes.txt"
    source.write_text("Notes diverses", encoding="utf-8")
    classification = LocalClassifier().classify(source)
    assert classification.needs_review is True or classification.confidence < 62
