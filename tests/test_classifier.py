from pathlib import Path

from mdjr_classeur.classifier import LocalClassifier, clean_filename


def test_classifies_math_td_from_name(tmp_path: Path):
    path = tmp_path / "TD_maths_integrales_chapitre_3.pdf"
    path.write_bytes(b"%PDF-1.4")
    result = LocalClassifier().classify(path)
    assert result.subject == "Mathématiques"
    assert result.category == "TD"
    assert result.confidence >= 70


def test_classifies_administrative_text_from_content(tmp_path: Path):
    path = tmp_path / "document_important.txt"
    path.write_text("Attestation d'inscription universitaire et certificat de scolarité", encoding="utf-8")
    result = LocalClassifier().classify(path)
    assert result.category == "Administratif"
    assert result.confidence >= 70


def test_title_comes_from_text_content(tmp_path: Path):
    path = tmp_path / "document_inconnu.txt"
    path.write_text("\n\nLes fonctions dérivées et leurs applications\nUn long développement de cours.", encoding="utf-8")
    result = LocalClassifier().classify(path)
    assert result.title == "Les fonctions dérivées et leurs applications"


def test_docx_content_is_analyzed(tmp_path: Path):
    from docx import Document
    path = tmp_path / "fichier_sans_nom.docx"
    document = Document()
    document.add_paragraph("Attestation de scolarité universitaire")
    document.save(path)
    result = LocalClassifier().classify(path)
    assert result.category == "Administratif"
    assert "Attestation" in result.title


def test_unknown_files_are_safe(tmp_path: Path):
    path = tmp_path / "scan_001.bin"
    path.write_bytes(b"binary")
    result = LocalClassifier().classify(path)
    assert result.subject == "À trier"
    assert result.category == "Autre"
    assert result.confidence < 50


def test_filename_is_safe():
    assert clean_filename('a<>:"/\\|?* b.pdf') == "a b.pdf"
