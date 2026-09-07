from __future__ import annotations

import os
import shutil
import subprocess
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


class LocalPDFOCR:
    """OCR PDF et images local via Poppler et Tesseract, sans réseau et avec limites strictes."""

    def __init__(self, max_pages: int = 12, dpi: int = 180, timeout_seconds: int = 90, languages: str = "fra+eng"):
        self.max_pages = max_pages
        self.dpi = dpi
        self.timeout_seconds = timeout_seconds
        self.languages = languages

    @property
    def available(self) -> bool:
        return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))

    @property
    def tesseract_available(self) -> bool:
        return bool(shutil.which("tesseract"))

    def extract(self, path: Path, max_chars: int = 30_000) -> OCRResult:
        if not self.available:
            return OCRResult("", "OCR indisponible : installer Tesseract et Poppler", error="tesseract ou pdftoppm absent")
        chunks: list[str] = []
        pages = 0
        try:
            with tempfile.TemporaryDirectory(prefix="classeur-ocr-") as temporary:
                prefix = str(Path(temporary) / "page")
                subprocess.run(
                    ["pdftoppm", "-f", "1", "-l", str(self.max_pages), "-r", str(self.dpi), "-png", str(path), prefix],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=self.timeout_seconds,
                )
                images = sorted(Path(temporary).glob("page-*.png"))
                if not images:
                    return OCRResult("", "OCR sans page exploitable", error="aucune page rasterisée")
                for image in images:
                    remaining = max_chars - sum(len(chunk) for chunk in chunks)
                    if remaining <= 0:
                        break
                    try:
                        result = subprocess.run(
                            ["tesseract", str(image), "stdout", "-l", self.languages, "--psm", "3"],
                            check=False,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=max(10, self.timeout_seconds // max(1, len(images))),
                        )
                    except subprocess.TimeoutExpired:
                        continue
                    if result.returncode != 0 and self.languages != "eng":
                        result = subprocess.run(
                            ["tesseract", str(image), "stdout", "-l", "eng", "--psm", "3"],
                            check=False,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=max(10, self.timeout_seconds // max(1, len(images))),
                        )
                    text = (result.stdout or "").strip()
                    if text:
                        chunks.append(text[:remaining])
                    pages += 1
            text = "\n\n".join(chunks)[:max_chars]
            if not text:
                return OCRResult("", "OCR terminé mais aucun texte fiable extrait", pages, "résultat vide")
            return OCRResult(text, "contenu lu par OCR local", pages)
        except (OSError, subprocess.SubprocessError) as exc:
            return OCRResult("", "OCR impossible : document conservé sans texte", pages, str(exc))

    def extract_image(self, path: Path, max_chars: int = 30_000) -> OCRResult:
        if not self.tesseract_available:
            return OCRResult("", "OCR indisponible : installer Tesseract", error="tesseract absent")
        try:
            result = subprocess.run(
                ["tesseract", str(path), "stdout", "-l", self.languages, "--psm", "3"],
                check=False, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=self.timeout_seconds,
            )
            if result.returncode != 0 and self.languages != "eng":
                result = subprocess.run(
                    ["tesseract", str(path), "stdout", "-l", "eng", "--psm", "3"],
                    check=False, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=self.timeout_seconds,
                )
            text = (result.stdout or "").strip()[:max_chars]
            if text:
                return OCRResult(text, "contenu lu par OCR image", 1)
            return OCRResult("", "OCR image : aucun texte détecté", 1, "résultat vide")
        except (OSError, subprocess.SubprocessError) as exc:
            return OCRResult("", "OCR image impossible", 0, str(exc))
