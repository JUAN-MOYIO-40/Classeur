from pathlib import Path

from mdjr_classeur.classifier import Classification, LocalClassifier
from mdjr_classeur.app import build_destination


def test_student_hierarchy_and_destination(tmp_path: Path):
    source = tmp_path / "Premiere_annee_physique_electromagnetisme_2024-2025_cours.txt"
    source.write_text(
        "Année 1 2024-2025\nCours de physique : électromagnétisme et loi de Gauss\n",
        encoding="utf-8",
    )
    classification = LocalClassifier().classify(source)
    assert classification.year in {"Année 1", "2024-2025"}
    assert classification.domain == "Sciences"
    assert classification.subject == "Physique"
    assert classification.topic in {"Électromagnétisme", "Électrostatique"}
    assert "Cours" in classification.category
    destination_dir, destination_file, _ = build_destination(tmp_path / "Classement", classification, ".txt", source.stem)
    assert "Sciences" in destination_dir.parts
    assert classification.topic in destination_dir.parts
    assert destination_file.suffix == ".txt"


def test_existing_hierarchy_is_reused(tmp_path: Path):
    root = tmp_path / "Classement"
    existing = root / "Année 1" / "Sciences" / "Physique" / "Électromagnétisme" / "Cours"
    existing.mkdir(parents=True)
    classification = Classification(
        "Physique", "Cours", 90, "test", "", "Champs électriques", "Année 1", "Sciences", "Électromagnétisme",
        ("Année 1", "Sciences", "Physique", "Électromagnétisme", "Cours"),
    )
    destination_dir, _, reason = build_destination(root, classification, ".pdf", "source")
    assert destination_dir == existing
    assert "réutilisé" in reason


def test_number_in_filename_is_not_an_academic_year(tmp_path: Path):
    source = tmp_path / "facture_2024_version_2.txt"
    source.write_text("Facture d'électricité du mois de mars", encoding="utf-8")
    classification = LocalClassifier().classify(source)
    assert classification.year == "2024"
    assert classification.subject != "Physique"


def test_l2_and_releve_are_hierarchical(tmp_path: Path):
    source = tmp_path / "L2_releve_notes_2025.pdf"
    source.write_text("Relevé de notes universitaires - résultats", encoding="utf-8")
    classification = LocalClassifier().classify(source)
    assert classification.year == "Année 2"
    assert classification.category == "Relevé de notes"
    assert classification.topic == "Relevé de notes"
    assert classification.needs_review is False or classification.confidence >= 40
