from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OCRResult:
    text: str
    status: str
    pages_read: int = 0
    error: str = ""


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}


def _find_tesseract() -> str | None:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
        for sub in ("tesseract", "_internal/tesseract"):
            p = base / sub / "tesseract.exe"
            if p.exists():
                return str(p)
    else:
        p = Path(__file__).resolve().parent.parent.parent / "tesseract" / "tesseract.exe"
        if p.exists():
            return str(p)
    if shutil.which("tesseract"):
        return "tesseract"
    default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if default.exists():
        return str(default)
    return None


def _find_tessdata() -> str | None:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
        for sub in ("tesseract/tessdata", "_internal/tesseract/tessdata"):
            d = base / sub
            if d.exists() and (d / "eng.traineddata").exists():
                return str(d)
    else:
        d = Path(__file__).resolve().parent.parent.parent / "tesseract" / "tessdata"
        if d.exists() and (d / "eng.traineddata").exists():
            return str(d)
    return None


_TESSERACT_CMD = _find_tesseract()
_TESSDATA_DIR = _find_tessdata()
if _TESSDATA_DIR:
    os.environ["TESSDATA_PREFIX"] = _TESSDATA_DIR


def _render_pdf_pages(path: Path, max_pages: int, dpi: int) -> tuple[Path | None, list[Path]]:
    """Rend les premières pages d'un PDF en PNG temporaires via PyMuPDF.

    Retourne le dossier temporaire et les images produites. Le dossier est
    rendu même quand la conversion échoue : l'appelant le supprime dans tous
    les cas, sinon un PDF illisible laisserait un répertoire orphelin à chaque
    tentative.
    """
    try:
        import pymupdf
    except ImportError:
        return None, []
    tmpdir = Path(tempfile.mkdtemp(prefix="classeur-ocr-"))
    images: list[Path] = []
    document = None
    try:
        document = pymupdf.open(str(path))
        matrix = pymupdf.Matrix(dpi / 72, dpi / 72)
        for index in range(min(max_pages, len(document))):
            target = tmpdir / f"page-{index:04d}.png"
            document[index].get_pixmap(matrix=matrix).save(str(target))
            images.append(target)
    except Exception:
        pass
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:
                pass
    return tmpdir, images


class LocalPDFOCR:
    """OCR PDF et images local via PyMuPDF + Tesseract, sans réseau et avec limites strictes."""

    def __init__(self, max_pages: int = 12, dpi: int = 180, timeout_seconds: int = 90, languages: str = "fra+eng"):
        self.max_pages = max_pages
        self.dpi = dpi
        self.timeout_seconds = timeout_seconds
        self.languages = languages

    @property
    def available(self) -> bool:
        return _TESSERACT_CMD is not None

    @property
    def tesseract_available(self) -> bool:
        return _TESSERACT_CMD is not None

    def _run_tesseract(self, image_path: Path, timeout: int) -> str:
        assert _TESSERACT_CMD is not None
        env = dict(os.environ)
        if _TESSDATA_DIR:
            env["TESSDATA_PREFIX"] = _TESSDATA_DIR
        try:
            result = subprocess.run(
                [_TESSERACT_CMD, str(image_path), "stdout", "-l", self.languages, "--psm", "3"],
                check=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            return ""
        if result.returncode != 0 and self.languages != "eng":
            try:
                result = subprocess.run(
                    [_TESSERACT_CMD, str(image_path), "stdout", "-l", "eng", "--psm", "3"],
                    check=False, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout, env=env,
                )
            except subprocess.TimeoutExpired:
                return ""
        return (result.stdout or "").strip()

    def extract(self, path: Path, max_chars: int = 30_000) -> OCRResult:
        if not self.available:
            return OCRResult("", "OCR indisponible : Tesseract non trouvé", error="tesseract absent")
        tmpdir, images = _render_pdf_pages(path, self.max_pages, self.dpi)
        chunks: list[str] = []
        pages = 0
        try:
            if not images:
                return OCRResult("", "OCR sans page exploitable", error="conversion PDF échouée")
            for image in images:
                remaining = max_chars - sum(len(c) for c in chunks)
                if remaining <= 0:
                    break
                timeout = max(10, self.timeout_seconds // max(1, len(images)))
                text = self._run_tesseract(image, timeout)
                if text:
                    chunks.append(text[:remaining])
                pages += 1
        finally:
            if tmpdir is not None:
                shutil.rmtree(tmpdir, ignore_errors=True)
        text = "\n\n".join(chunks)[:max_chars]
        if not text:
            return OCRResult("", "OCR terminé mais aucun texte fiable extrait", pages, "résultat vide")
        return OCRResult(text, "contenu lu par OCR local", pages)

    def extract_image(self, path: Path, max_chars: int = 30_000) -> OCRResult:
        if not self.tesseract_available:
            return OCRResult("", "OCR indisponible : Tesseract non trouvé", error="tesseract absent")
        text = self._run_tesseract(path, self.timeout_seconds)[:max_chars]
        if text:
            return OCRResult(text, "contenu lu par OCR image", 1)
        return OCRResult("", "OCR image : aucun texte détecté", 1, "résultat vide")
