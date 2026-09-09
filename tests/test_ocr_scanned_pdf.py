import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from mdjr_classeur.classifier import LocalClassifier
from mdjr_classeur.infrastructure.ocr import LocalPDFOCR


def _make_scanned_pdf(path: Path) -> None:
    image = Image.new("RGB", (1600, 500), "white")
    draw = ImageDraw.Draw(image)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 72) if Path(font_path).exists() else ImageFont.load_default()
    draw.text((80, 100), "COURS DE PHYSIQUE", fill="black", font=font)
    draw.text((80, 230), "Electromagnetisme et champ electrique", fill="black", font=font)
    image.save(path, "PDF", resolution=150.0)


@pytest.mark.skipif(not LocalPDFOCR().available, reason="Tesseract et Poppler ne sont pas disponibles")
def test_scanned_pdf_is_read_by_local_ocr(tmp_path: Path):
    pdf = tmp_path / "scan.pdf"
    _make_scanned_pdf(pdf)
    result = LocalPDFOCR(max_pages=1).extract(pdf)
    assert "physique" in result.text.casefold()
    assert "ocr" in result.status.casefold()
    classification = LocalClassifier().classify(pdf)
    assert classification.content_status == "contenu lu par OCR local"
    assert classification.subject == "Physique"


def _classeur_tmpdirs() -> set[Path]:
    return set(Path(tempfile.gettempdir()).glob("classeur-ocr-*"))


def test_unreadable_pdf_leaves_no_temporary_directory(tmp_path: Path):
    """Un PDF illisible ne doit pas laisser de dossier temporaire orphelin."""
    broken = tmp_path / "casse.pdf"
    broken.write_bytes(b"%PDF-1.4\nceci n'est pas un vrai PDF")
    before = _classeur_tmpdirs()
    result = LocalPDFOCR(max_pages=1).extract(broken)
    assert result.text == ""
    assert _classeur_tmpdirs() == before


@pytest.mark.skipif(not LocalPDFOCR().available, reason="Tesseract n'est pas disponible")
def test_successful_ocr_leaves_no_temporary_directory(tmp_path: Path):
    pdf = tmp_path / "scan.pdf"
    _make_scanned_pdf(pdf)
    before = _classeur_tmpdirs()
    LocalPDFOCR(max_pages=1).extract(pdf)
    assert _classeur_tmpdirs() == before
