from pathlib import Path

from mdjr_classeur.dedupe import scan_duplicates
from mdjr_classeur.classifier import Classification
from mdjr_classeur.app import build_destination


def test_reuses_existing_subject_and_category(tmp_path: Path):
    root = tmp_path / "classement"
    existing = root / "Maths" / "Travaux dirigés"
    existing.mkdir(parents=True)
    classification = Classification("Mathématiques", "TD", 90, "test", title="Integrales")
    destination_dir, destination_file, reason = build_destination(root, classification, ".pdf", "td_maths")
    assert destination_dir == existing
    assert destination_file.parent == existing
    assert "réutilisé" in reason


def test_detects_exact_duplicate_files(tmp_path: Path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    (source / "a.txt").write_text("contenu identique", encoding="utf-8")
    (destination / "copie.txt").write_text("contenu identique", encoding="utf-8")
    report = scan_duplicates([source, destination])
    assert report.total_file_duplicates == 1
    assert len(report.file_groups) == 1


def test_detects_equivalent_folders(tmp_path: Path):
    root = tmp_path / "root"
    first = root / "premier"
    second = root / "second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "cours.txt").write_text("même leçon", encoding="utf-8")
    (second / "cours.txt").write_text("même leçon", encoding="utf-8")
    report = scan_duplicates([root])
    assert report.total_folder_duplicates >= 1
    assert any(set(group.folders) == {first, second} for group in report.folder_groups)
