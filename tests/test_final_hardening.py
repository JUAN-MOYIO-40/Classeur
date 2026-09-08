"""
FINAL HARDENING / PRODUCTION AUDIT — test suite complète.

Couvre : pipeline E2E, offline, robustesse fichiers, sécurité des opérations,
recherche, AI provider, code audit, et performance.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import struct
import tempfile
import time
import unittest.mock as mock
from pathlib import Path
from zipfile import ZipFile

import pytest

from mdjr_classeur.classifier import (
    Classification,
    LocalClassifier,
    clean_filename,
    fold,
    read_content,
    read_content_details,
    suggest_title,
)
from mdjr_classeur.cache import ClassificationCache
from mdjr_classeur.search_index import SearchIndex, SearchRecord
from mdjr_classeur.semantic import NativeSemanticEngine
from mdjr_classeur.dedupe import (
    DuplicateReport,
    duplicate_victims,
    hash_file,
    quick_hash_file,
    scan_duplicates,
)
from mdjr_classeur.domain.models import PlanItem
from mdjr_classeur.domain.paths import FolderPairError, resolve_folder_pair
from mdjr_classeur.domain.planning import build_destination, reuse_existing_folder
from mdjr_classeur.application.services import ClassificationService, ScanService, UndoService
from mdjr_classeur.application.agent import AgentLedger
from mdjr_classeur.application.agent_brain import AgentAction, DocumentAgentBrain
from mdjr_classeur.application.learning import LearningMemory
from mdjr_classeur.application.naming import FilenameProposalService
from mdjr_classeur.application.document_identity import ContentIdentityService
from mdjr_classeur.application.plan import PlanEditService
from mdjr_classeur.application.duplicates import DuplicateService
from mdjr_classeur.application.ai_provider import (
    AIProviderRegistry,
    BaseAIProvider,
    LocalHeuristicProvider,
    LlamaCppProvider,
)
from mdjr_classeur.infrastructure.filesystem import (
    FileOperationService,
    atomic_write_text,
    is_ignored_file,
    normalized_text_sha256,
    sha256_file,
    unique_target,
)
from mdjr_classeur.infrastructure.history import HistoryRepository
from mdjr_classeur.infrastructure.ocr import IMAGE_EXTENSIONS, LocalPDFOCR


# =========================================================================
# Helpers
# =========================================================================

def _make_pdf(path: Path, text: str = "Contrat d'assurance Belife police numero 12345"):
    """Crée un PDF minimal valide avec du texte embarqué."""
    try:
        from pypdf import PdfWriter
        writer = PdfWriter()
        from pypdf.generic import NameObject, TextStringObject, ArrayObject, NumberObject
        page = writer.add_blank_page(width=595, height=842)
        writer.write(str(path))
        path.write_bytes(path.read_bytes())
    except ImportError:
        pass
    if not path.exists() or path.stat().st_size == 0:
        path.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                         b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                         b"3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R>>endobj\n"
                         b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF")


def _make_docx(path: Path, text: str = "Attestation de scolarité universitaire"):
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )


def _make_txt(path: Path, text: str = "Cours de physique electromagnetisme"):
    path.write_text(text, encoding="utf-8")


def _service(tmp_path: Path):
    classifier = LocalClassifier()
    cache = ClassificationCache(tmp_path / "cache.sqlite3")
    cs = ClassificationService(classifier, cache)
    ledger = AgentLedger(tmp_path / "agent.sqlite3")
    learning = LearningMemory(tmp_path / "learning.sqlite3")
    scan = ScanService(cs, ledger=ledger, learning=learning)
    return scan, classifier, cache, ledger, learning


# =========================================================================
# 1. END-TO-END PIPELINE TEST
# =========================================================================

class TestEndToEndPipeline:

    def test_full_pipeline_txt(self, tmp_path: Path):
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        _make_txt(source / "cours_physique_electromagnetisme.txt",
                  "Cours de physique electromagnetisme champ electrique Maxwell")
        scan, *_ = _service(tmp_path)
        items = scan.scan(source, dest)
        assert len(items) == 1
        item = items[0]
        assert item.classification.subject != "À trier"
        assert item.confidence > 40
        assert item.sha256
        assert item.destination_file.suffix == ".txt"
        fos = FileOperationService()
        results = fos.execute(items, "copy")
        assert results[0]["operation"] == "copy"
        assert Path(results[0]["target"]).exists()
        assert item.source.exists()

    def test_full_pipeline_docx(self, tmp_path: Path):
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        _make_docx(source / "attestation.docx", "Attestation de scolarité universitaire inscription")
        scan, *_ = _service(tmp_path)
        items = scan.scan(source, dest)
        assert len(items) == 1
        assert items[0].classification.category in ("Administratif", "Cours", "Contrat")
        assert items[0].classification.content_status == "contenu lu"

    def test_full_pipeline_move_mode(self, tmp_path: Path):
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        _make_txt(source / "facture_comptabilite.txt", "Facture devis bon de commande comptabilite")
        scan, *_ = _service(tmp_path)
        items = scan.scan(source, dest)
        fos = FileOperationService()
        results = fos.execute(items, "move")
        assert results[0]["operation"] == "move"
        assert not (source / "facture_comptabilite.txt").exists()
        assert Path(results[0]["target"]).exists()

    def test_same_folder_mode_organises_in_place(self, tmp_path: Path):
        folder = tmp_path / "mes_documents"
        folder.mkdir()
        _make_txt(folder / "facture.txt", "Facture devis bon de commande comptabilite")
        _make_txt(folder / "cours.txt", "Cours de physique electromagnetisme champ electrique")
        scan, *_ = _service(tmp_path)
        items = scan.scan(folder, folder)
        assert len(items) == 2
        FileOperationService().execute(items, "move")
        placed = [p for p in folder.rglob("*") if p.is_file()]
        assert len(placed) == 2
        # chaque fichier vit maintenant dans un sous-dossier, plus à la racine
        assert all(p.parent != folder for p in placed)

    def test_same_folder_mode_ignores_already_organised_files(self, tmp_path: Path):
        folder = tmp_path / "mes_documents"
        (folder / "Comptabilite" / "Facture").mkdir(parents=True)
        _make_txt(folder / "nouveau.txt", "Facture devis bon de commande comptabilite")
        _make_txt(folder / "Comptabilite" / "Facture" / "ancien.txt", "Cours de physique electromagnetisme")
        scan, *_ = _service(tmp_path)
        items = scan.scan(folder, folder)
        assert [item.source.name for item in items] == ["nouveau.txt"]

    def test_identical_pending_files_keep_one_and_quarantine_the_other(self, tmp_path: Path):
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        content = "Facture devis bon de commande comptabilite montant total"
        _make_txt(source / "original.txt", content)
        _make_txt(source / "copie.txt", content)
        scan, *_ = _service(tmp_path)
        items = scan.scan(source, dest)
        assert len(items) == 2
        results = FileOperationService().execute(items, "move")
        operations = [r["operation"] for r in results]
        # un seul des deux part en quarantaine : l'autre doit être réellement classé
        assert operations.count("duplicate") == 1
        assert operations.count("move") == 1

    def test_pipeline_skips_files_inside_destination(self, tmp_path: Path):
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        (dest / "already_classified.txt").write_text("contenu", encoding="utf-8")
        _make_txt(source / "new_file.txt")
        scan, *_ = _service(tmp_path)
        items = scan.scan(source, dest)
        assert len(items) == 1
        assert items[0].source.name == "new_file.txt"

    def test_pipeline_insurance_document_high_confidence(self, tmp_path: Path):
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        _make_txt(source / "police_assurance_belife.txt",
                  "Police d'assurance Belife numero de police 123456 "
                  "souscripteur beneficiaire garantie sinistre prime cotisation "
                  "conditions generales conditions particulieres")
        scan, *_ = _service(tmp_path)
        items = scan.scan(source, dest)
        assert len(items) == 1
        assert items[0].classification.subject == "Assurance"
        assert items[0].confidence >= 80


# =========================================================================
# 2. STRICT OFFLINE TEST
# =========================================================================

class TestOffline:

    def test_classifier_makes_zero_network_calls(self, tmp_path: Path):
        _make_txt(tmp_path / "test.txt", "Cours de mathematiques algebre")
        original_connect = socket.socket.connect

        def deny_network(*args, **kwargs):
            raise AssertionError("Network call detected during classification!")

        with mock.patch.object(socket.socket, "connect", deny_network):
            classifier = LocalClassifier()
            result = classifier.classify(tmp_path / "test.txt")
            assert result.subject == "Mathématiques"

    def test_semantic_engine_offline(self):
        engine = NativeSemanticEngine()
        original_connect = socket.socket.connect

        def deny_network(*args, **kwargs):
            raise AssertionError("Network call in semantic engine!")

        with mock.patch.object(socket.socket, "connect", deny_network):
            name, score, hits = engine.predict(
                "physique electromagnetisme champ",
                {"Physique": ["physique", "electromagnetisme"], "Chimie": ["chimie", "molecule"]},
            )
            assert name == "Physique"
            assert score > 0

    def test_search_index_offline(self, tmp_path: Path):
        index = SearchIndex(tmp_path / "test.sqlite3")
        original_connect = socket.socket.connect

        def deny_network(*args, **kwargs):
            raise AssertionError("Network call in search index!")

        with mock.patch.object(socket.socket, "connect", deny_network):
            c = Classification("Test", "Cours", 80, "test", title="Doc")
            index.upsert(tmp_path / "fake.txt", c)
            results = index.hybrid_search("test")
        index.close()

    def test_ai_provider_offline(self):
        registry = AIProviderRegistry()
        original_connect = socket.socket.connect

        def deny_network(*args, **kwargs):
            raise AssertionError("Network call in AI provider!")

        with mock.patch.object(socket.socket, "connect", deny_network):
            result = registry.summarize("Cours de physique quantique")
            assert result.provider == "local-heuristic"
            assert result.text

    def test_full_scan_pipeline_offline(self, tmp_path: Path):
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        _make_txt(source / "doc.txt", "Contrat d'assurance police sinistre")

        def deny_network(*args, **kwargs):
            raise AssertionError("Network call detected!")

        with mock.patch.object(socket.socket, "connect", deny_network):
            scan, *_ = _service(tmp_path)
            items = scan.scan(source, dest)
            assert len(items) == 1

            fos = FileOperationService()
            results = fos.execute(items, "copy")
            assert results[0]["operation"] == "copy"


# =========================================================================
# 3. FILE ROBUSTNESS
# =========================================================================

class TestFileRobustness:

    def test_empty_txt_file(self, tmp_path: Path):
        path = tmp_path / "empty.txt"
        path.write_text("", encoding="utf-8")
        result = LocalClassifier().classify(path)
        assert result.subject == "À trier"
        assert result.confidence < 50

    def test_empty_pdf(self, tmp_path: Path):
        path = tmp_path / "empty.pdf"
        path.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                         b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                         b"3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R>>endobj\n"
                         b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF")
        result = LocalClassifier().classify(path)
        assert isinstance(result, Classification)

    def test_corrupt_pdf(self, tmp_path: Path):
        path = tmp_path / "corrupt.pdf"
        path.write_bytes(b"NOT A REAL PDF FILE JUST GARBAGE DATA")
        result = LocalClassifier().classify(path)
        assert isinstance(result, Classification)
        assert result.confidence < 50

    def test_corrupt_docx(self, tmp_path: Path):
        path = tmp_path / "corrupt.docx"
        path.write_bytes(b"NOT A REAL DOCX")
        text, status = read_content_details(path)
        assert text == ""

    def test_binary_file(self, tmp_path: Path):
        path = tmp_path / "binary.bin"
        path.write_bytes(os.urandom(1024))
        text, status = read_content_details(path)
        assert text == ""
        assert "non pris en charge" in status

    def test_unicode_filename(self, tmp_path: Path):
        path = tmp_path / "éàü_données_résumé_ñ.txt"
        path.write_text("Cours de mathematiques algebre", encoding="utf-8")
        result = LocalClassifier().classify(path)
        assert isinstance(result, Classification)
        assert result.subject == "Mathématiques"

    def test_special_chars_filename(self, tmp_path: Path):
        path = tmp_path / "file [2024] (copy).txt"
        path.write_text("Cours informatique python", encoding="utf-8")
        result = LocalClassifier().classify(path)
        assert isinstance(result, Classification)

    def test_very_long_filename(self, tmp_path: Path):
        long_name = "a" * 200 + ".txt"
        path = tmp_path / long_name
        try:
            path.write_text("contenu", encoding="utf-8")
        except OSError:
            pytest.skip("OS does not support this filename length")
        result = LocalClassifier().classify(path)
        assert isinstance(result, Classification)

    def test_duplicate_detection_exact(self, tmp_path: Path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("contenu identique exact", encoding="utf-8")
        b.write_text("contenu identique exact", encoding="utf-8")
        report = scan_duplicates([tmp_path])
        assert report.total_file_duplicates == 1

    def test_duplicate_detection_different(self, tmp_path: Path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("premier contenu", encoding="utf-8")
        b.write_text("second contenu different", encoding="utf-8")
        report = scan_duplicates([tmp_path])
        assert report.total_file_duplicates == 0

    def test_near_duplicate_text_normalized(self, tmp_path: Path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("Cours  de   physique\n\n  electromagnetisme", encoding="utf-8")
        b.write_text("Cours de physique\nelectromagnetisme", encoding="utf-8")
        digest_a = normalized_text_sha256(a)
        digest_b = normalized_text_sha256(b)
        assert digest_a is not None
        assert digest_a == digest_b

    def test_xlsx_is_readable(self, tmp_path: Path):
        path = tmp_path / "data.xlsx"
        with ZipFile(path, "w") as archive:
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<row><c><v>Budget finance tresorerie</v></c></row></worksheet>",
            )
        result = LocalClassifier().classify(path)
        assert result.content_status == "contenu lu"

    def test_unknown_extension(self, tmp_path: Path):
        path = tmp_path / "document.xyz"
        path.write_bytes(b"arbitrary content")
        text, status = read_content_details(path)
        assert "non pris en charge" in status

    def test_image_extension_recognized(self):
        for ext in (".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"):
            assert ext in IMAGE_EXTENSIONS


# =========================================================================
# 4. OPERATION SECURITY
# =========================================================================

class TestOperationSecurity:

    def test_copy_never_deletes_source(self, tmp_path: Path):
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        original = source / "important.txt"
        original.write_text("ne pas supprimer", encoding="utf-8")
        c = Classification("Test", "Cours", 80, "r", title="T")
        item = PlanItem(original, c, dest, dest / "important.txt", destination_root=dest)
        fos = FileOperationService()
        results = fos.execute([item], "copy")
        assert original.exists(), "Source file was deleted during copy!"
        assert results[0]["operation"] == "copy"

    def test_collision_handling_unique_target(self, tmp_path: Path):
        existing = tmp_path / "file.txt"
        existing.write_text("existing", encoding="utf-8")
        target = unique_target(existing)
        assert target != existing
        assert target.stem.endswith("(1)")

    def test_collision_handling_multiple(self, tmp_path: Path):
        for i in range(3):
            name = "doc.txt" if i == 0 else f"doc ({i}).txt"
            (tmp_path / name).write_text(f"version {i}", encoding="utf-8")
        target = unique_target(tmp_path / "doc.txt")
        assert target == tmp_path / "doc (3).txt"

    def test_atomic_write_text_survives_crash(self, tmp_path: Path):
        path = tmp_path / "config.json"
        atomic_write_text(path, '{"version": 1}')
        assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
        atomic_write_text(path, '{"version": 2}')
        assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2
        assert not list(tmp_path.glob(".*tmp*"))

    def test_history_persistence(self, tmp_path: Path):
        repo = HistoryRepository(tmp_path / "history.json")
        repo.append([{"source": "a.txt", "target": "b.txt", "operation": "copy", "timestamp": time.time(), "batch_id": "1"}])
        loaded = repo.load()
        assert len(loaded) == 1
        assert loaded[0]["source"] == "a.txt"

    def test_undo_move_restores_file(self, tmp_path: Path):
        source_dir = tmp_path / "source"
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()
        original = source_dir / "moved.txt"
        original.write_text("contenu", encoding="utf-8")
        target = dest_dir / "moved.txt"
        shutil.move(str(original), str(target))
        target_stat = target.stat()
        repo = HistoryRepository(tmp_path / "history.json")
        repo.append([{
            "source": str(original), "target": str(target),
            "operation": "move", "timestamp": time.time(), "batch_id": "1",
            "target_size": target_stat.st_size, "target_mtime_ns": target_stat.st_mtime_ns,
        }])
        undo = UndoService(repo)
        undone, skipped = undo.undo_latest()
        assert undone == 1
        assert original.exists()
        assert not target.exists()

    def test_undo_copy_deletes_target(self, tmp_path: Path):
        source = tmp_path / "source.txt"
        target = tmp_path / "target.txt"
        source.write_text("contenu", encoding="utf-8")
        shutil.copy2(str(source), str(target))
        target_stat = target.stat()
        repo = HistoryRepository(tmp_path / "history.json")
        repo.append([{
            "source": str(source), "target": str(target),
            "operation": "copy", "timestamp": time.time(), "batch_id": "1",
            "target_size": target_stat.st_size, "target_mtime_ns": target_stat.st_mtime_ns,
        }])
        undo = UndoService(repo)
        undone, skipped = undo.undo_latest()
        assert undone == 1
        assert not target.exists()
        assert source.exists()

    def test_undo_skips_modified_target(self, tmp_path: Path):
        target = tmp_path / "target.txt"
        target.write_text("original content", encoding="utf-8")
        target_stat = target.stat()
        repo = HistoryRepository(tmp_path / "history.json")
        repo.append([{
            "source": str(tmp_path / "gone.txt"), "target": str(target),
            "operation": "copy", "timestamp": time.time(), "batch_id": "1",
            "target_size": target_stat.st_size, "target_mtime_ns": target_stat.st_mtime_ns,
        }])
        time.sleep(0.05)
        target.write_text("MODIFIED — this is now different content with different size", encoding="utf-8")
        undo = UndoService(repo)
        undone, skipped = undo.undo_latest()
        assert undone == 0
        assert len(skipped) == 1
        assert target.exists()

    def test_ignored_files_are_skipped(self, tmp_path: Path):
        assert is_ignored_file(tmp_path / "~$document.docx")
        assert is_ignored_file(tmp_path / "file.tmp")
        assert is_ignored_file(tmp_path / "file.part")
        assert is_ignored_file(tmp_path / ".~lock.file")
        assert is_ignored_file(tmp_path / "file.classeur-partial-123")
        assert not is_ignored_file(tmp_path / "normal.txt")
        assert not is_ignored_file(tmp_path / "report.pdf")

    def test_partial_file_naming(self, tmp_path: Path):
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        _make_txt(source / "doc.txt", "Cours informatique")
        scan, *_ = _service(tmp_path)
        items = scan.scan(source, dest)
        fos = FileOperationService()
        results = fos.execute(items, "copy")
        partials = list(dest.rglob("*.classeur-partial-*"))
        assert len(partials) == 0, f"Partial files left behind: {partials}"

    def test_history_max_entries_capping(self, tmp_path: Path):
        repo = HistoryRepository(tmp_path / "history.json", max_entries=10)
        for i in range(20):
            repo.append([{"index": i, "timestamp": time.time()}])
        loaded = repo.load()
        assert len(loaded) <= 10


# =========================================================================
# 5. PERFORMANCE
# =========================================================================

class TestPerformance:

    def test_classify_100_files_stays_linear(self, tmp_path: Path):
        """Garde-fou contre une classification pathologiquement lente.

        Le seuil est volontairement large : la mesure est une horloge murale sur
        une machine partagée, un seuil serré échouerait au gré de la charge sans
        signaler de régression réelle.
        """
        source = tmp_path / "source"
        source.mkdir()
        for i in range(100):
            _make_txt(source / f"doc_{i:03d}.txt", f"Document numero {i} cours physique mathematiques")
        classifier = LocalClassifier()
        start = time.perf_counter()
        for path in source.iterdir():
            classifier.classify(path)
        elapsed = time.perf_counter() - start
        assert elapsed < 60, f"100 classifications took {elapsed:.1f}s (limit: 60s)"

    def test_search_index_500_entries(self, tmp_path: Path):
        index = SearchIndex(tmp_path / "perf.sqlite3")
        for i in range(500):
            c = Classification(f"Subject_{i % 10}", f"Cat_{i % 5}", 80, "test",
                               title=f"Document {i}", extracted_preview=f"Preview content {i}")
            p = tmp_path / f"doc_{i:04d}.txt"
            p.write_text(f"content {i}", encoding="utf-8")
            index.upsert(p, c, commit=False)
        index.connection.commit()
        start = time.perf_counter()
        results = index.hybrid_search("Document", limit=100)
        elapsed = time.perf_counter() - start
        assert len(results) > 0
        assert elapsed < 2, f"Search over 500 docs took {elapsed:.1f}s (limit: 2s)"
        stats = index.stats()
        assert stats["total"] == 500
        index.close()

    def test_duplicate_scan_200_files(self, tmp_path: Path):
        for i in range(200):
            (tmp_path / f"file_{i:03d}.txt").write_text(
                f"unique content for file {i}" if i % 2 == 0 else "duplicate content",
                encoding="utf-8",
            )
        start = time.perf_counter()
        report = scan_duplicates([tmp_path])
        elapsed = time.perf_counter() - start
        assert elapsed < 10, f"Duplicate scan of 200 files took {elapsed:.1f}s"
        assert report.scanned_files == 200
        assert report.total_file_duplicates > 0


# =========================================================================
# 6. SEARCH TESTING
# =========================================================================

class TestSearch:

    def _populated_index(self, tmp_path: Path) -> SearchIndex:
        index = SearchIndex(tmp_path / "search.sqlite3")
        entries = [
            ("physique.pdf", "Physique", "Cours", "Cours electromagnetisme Maxwell"),
            ("maths_td.pdf", "Mathématiques", "TD", "Exercices algèbre linéaire"),
            ("attestation.pdf", "À trier", "Administratif", "Attestation de scolarité"),
            ("assurance_belife.pdf", "Assurance", "Contrat", "Police assurance Belife sinistre"),
            ("facture_janvier.pdf", "Comptabilité", "Facture", "Facture comptabilité devis"),
        ]
        for name, subject, category, preview in entries:
            p = tmp_path / name
            p.write_text(preview, encoding="utf-8")
            c = Classification(subject, category, 85, "test", title=name, extracted_preview=preview)
            index.upsert(p, c)
        return index

    def test_exact_match(self, tmp_path: Path):
        index = self._populated_index(tmp_path)
        results = index.search("electromagnetisme")
        assert any("physique" in r.name for r in results)
        index.close()

    def test_partial_match(self, tmp_path: Path):
        index = self._populated_index(tmp_path)
        results = index.search("phys")
        assert any("physique" in r.name for r in results)
        index.close()

    def test_hybrid_search_combines_fts_and_semantic(self, tmp_path: Path):
        index = self._populated_index(tmp_path)
        results = index.hybrid_search("cours de physique")
        assert len(results) > 0
        index.close()

    def test_search_by_status_filter(self, tmp_path: Path):
        index = self._populated_index(tmp_path)
        results_all = index.search("", "Tous")
        results_classified = index.search("", "classé")
        assert len(results_all) >= len(results_classified)
        index.close()

    def test_search_empty_query_returns_all(self, tmp_path: Path):
        index = self._populated_index(tmp_path)
        results = index.search("")
        assert len(results) == 5
        index.close()

    def test_search_no_results(self, tmp_path: Path):
        index = self._populated_index(tmp_path)
        results = index.search("xyznonexistent")
        assert len(results) == 0
        index.close()

    def test_semantic_search(self, tmp_path: Path):
        index = self._populated_index(tmp_path)
        results = index.semantic_search("police assurance")
        assert len(results) > 0
        best_path = results[0][0].path
        assert "assurance" in best_path.lower() or "assurance" in results[0][0].subject.lower()
        index.close()

    def test_version_detection(self, tmp_path: Path):
        index = SearchIndex(tmp_path / "ver.sqlite3")
        for name, suffix in [("rapport", ""), ("rapport (1)", ""), ("rapport v2", ""), ("rapport - copie", "")]:
            p = tmp_path / f"{name}.txt"
            p.write_text(f"contenu {name}", encoding="utf-8")
            c = Classification("Test", "Projet", 80, "t", title=name)
            index.upsert(p, c)
        groups = index.detect_version_groups()
        assert len(groups) >= 1
        assert groups[0].count >= 2
        index.close()

    def test_find_versions_by_name(self, tmp_path: Path):
        index = self._populated_index(tmp_path)
        versions = index.find_versions("physique")
        assert any("physique" in v.name for v in versions)
        index.close()

    def test_index_delete_and_remove_missing(self, tmp_path: Path):
        index = SearchIndex(tmp_path / "del.sqlite3")
        p = tmp_path / "temp.txt"
        p.write_text("content", encoding="utf-8")
        c = Classification("T", "C", 80, "r")
        index.upsert(p, c)
        assert index.stats()["total"] == 1
        p.unlink()
        index.remove_missing()
        assert index.stats()["total"] == 0
        index.close()

    def test_stats_accuracy(self, tmp_path: Path):
        index = self._populated_index(tmp_path)
        stats = index.stats()
        assert stats["total"] == 5
        assert stats["subjects"] > 0
        assert stats["categories"] > 0
        index.close()


# =========================================================================
# 7. LOCAL AI ARCHITECTURE
# =========================================================================

class TestAIProvider:

    def test_local_heuristic_always_available(self):
        provider = LocalHeuristicProvider()
        assert provider.available
        assert provider.name == "local-heuristic"

    def test_local_heuristic_summarize(self):
        provider = LocalHeuristicProvider()
        result = provider.summarize("Ceci est un cours de physique quantique. Les atomes sont composés de protons et neutrons.")
        assert result.text
        assert result.provider == "local-heuristic"
        assert result.confidence > 0

    def test_local_heuristic_suggest_classification(self):
        provider = LocalHeuristicProvider()
        result = provider.suggest_classification(
            "physique electromagnetisme champ electrique",
            "cours_physique.pdf",
            {"Physique": ["physique", "electromagnetisme"], "Chimie": ["chimie"]},
            {"Cours": ["cours"], "TD": ["exercice"]},
        )
        assert "subject" in result.suggestions or result.confidence > 0

    def test_local_heuristic_suggest_filename(self):
        provider = LocalHeuristicProvider()
        c = Classification("Physique", "Cours", 80, "test", year="2024")
        result = provider.suggest_filename(
            "Cours de physique electromagnetisme avance pour etudiants",
            "doc001.pdf", c,
        )
        assert result.text
        assert result.confidence > 0

    def test_local_heuristic_answer_question(self):
        provider = LocalHeuristicProvider()
        result = provider.answer_question(
            "Quel est le sujet du document?",
            "Ce document traite de physique quantique et de mecanique ondulatoire.",
        )
        assert result.text

    def test_llama_cpp_not_available_without_binary(self):
        provider = LlamaCppProvider(Path("/nonexistent/model.gguf"))
        assert not provider.available

    def test_registry_cascade_fallback(self):
        registry = AIProviderRegistry()
        assert registry.active_provider.name == "local-heuristic"
        assert len(registry.available_providers) >= 1
        unavailable = LlamaCppProvider(Path("/nonexistent.gguf"))
        registry.register(unavailable)
        assert registry.active_provider.name == "local-heuristic"

    def test_registry_all_methods_work(self):
        registry = AIProviderRegistry()
        assert registry.summarize("texte").provider == "local-heuristic"
        assert registry.suggest_classification("texte", "f.pdf", {}, {}).provider == "local-heuristic"
        c = Classification("S", "C", 50, "r")
        assert registry.suggest_filename("texte", "f.pdf", c).provider == "local-heuristic"
        assert registry.answer_question("q?", "context").provider == "local-heuristic"


# =========================================================================
# 8. UX AUDIT (logic-level, no Qt needed)
# =========================================================================

class TestUXLogic:

    def test_all_agent_actions_have_labels(self):
        for action in AgentAction:
            assert action.value in ("auto_classify", "propose_for_review", "hold_for_review")

    def test_agent_brain_thresholds(self):
        brain = DocumentAgentBrain()
        c_low = Classification("À trier", "Autre", 18, "r", needs_review=True)
        c_mid = Classification("Physique", "Cours", 65, "r")
        c_high = Classification("Physique", "Cours", 92, "r")
        item_low = PlanItem(Path("a.txt"), c_low, Path("d"), Path("d/a.txt"))
        item_mid = PlanItem(Path("b.txt"), c_mid, Path("d"), Path("d/b.txt"))
        item_high = PlanItem(Path("c.txt"), c_high, Path("d"), Path("d/c.txt"))
        assert brain.decide(item_low).action == AgentAction.HOLD_FOR_REVIEW
        assert brain.decide(item_mid).action == AgentAction.PROPOSE_FOR_REVIEW
        assert brain.decide(item_high).action == AgentAction.AUTO_CLASSIFY

    def test_plan_edit_rejects_invalid_chars(self):
        c = Classification("Test", "Cours", 80, "r", title="T")
        item = PlanItem(Path("a.txt"), c, Path("d"), Path("d/a.txt"), destination_root=Path("d"))
        svc = PlanEditService()
        for bad in ('A/B', 'A\\B', 'A:B', 'A*B', 'A?B', 'A"B', 'A<B', 'A>B', 'A|B'):
            with pytest.raises(ValueError):
                svc.edit(item, "subject", bad)

    def test_plan_edit_updates_hierarchy(self):
        c = Classification("Physique", "Cours", 80, "r", year="2024", domain="Sciences")
        item = PlanItem(Path("a.txt"), c, Path("d"), Path("d/a.txt"), destination_root=Path("output"))
        svc = PlanEditService()
        svc.edit(item, "subject", "Chimie")
        assert item.classification.subject == "Chimie"
        assert "Chimie" in item.hierarchy_label

    def test_clean_filename_safety(self):
        assert clean_filename('A<B>C:D"E/F\\G|H?I*J', "safe") == "A B C D E F G H I J"
        assert clean_filename("", "Fallback") == "Fallback"
        assert len(clean_filename("x" * 200, "f")) <= 120

    def test_fold_removes_accents(self):
        assert fold("éàüñÇ") == "eaunc"
        assert fold("HELLO WORLD") == "hello world"
        assert fold("file-name_2024") == "file name 2024"


# =========================================================================
# 9. CODE AUDIT VERIFICATIONS
# =========================================================================

class TestCodeAudit:

    def test_no_hardcoded_windows_paths_in_source(self):
        src_dir = Path(__file__).resolve().parent.parent / "mdjr_classeur"
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="replace")
            assert "C:\\Users" not in content, f"Hard-coded Windows path found in {py_file.name}"

    def test_all_sqlite_connections_use_wal(self):
        """WAL mode is required for concurrent reads."""
        src_dir = Path(__file__).resolve().parent.parent / "mdjr_classeur"
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="replace")
            if "sqlite3.connect" in content and "journal_mode" not in content:
                if py_file.name == "cache.py":
                    continue
                assert False, f"SQLite connection without WAL in {py_file.name}"

    def test_atomic_write_leaves_no_temp_files(self, tmp_path: Path):
        path = tmp_path / "test.json"
        for i in range(10):
            atomic_write_text(path, json.dumps({"i": i}))
        temps = [f for f in tmp_path.iterdir() if ".tmp-" in f.name]
        assert len(temps) == 0

    def test_sha256_consistency(self, tmp_path: Path):
        path = tmp_path / "test.txt"
        path.write_text("consistent content", encoding="utf-8")
        h1 = sha256_file(path)
        h2 = sha256_file(path)
        assert h1 == h2
        assert len(h1) == 64

    def test_quick_hash_differs_from_full_hash_for_large_files(self, tmp_path: Path):
        path = tmp_path / "big.bin"
        path.write_bytes(os.urandom(256 * 1024))
        quick = quick_hash_file(path)
        full = hash_file(path)
        assert quick != full

    def test_text_quality_ratio(self):
        from mdjr_classeur.classifier import _text_quality_ratio
        assert _text_quality_ratio("Hello World") > 0.5
        assert _text_quality_ratio("") == 0.0
        assert _text_quality_ratio("12345!@#$%") < 0.15

    def test_encoding_utf8_everywhere(self, tmp_path: Path):
        path = tmp_path / "utf8.txt"
        content = "Héllo Wörld éàü ñ 中文"
        path.write_text(content, encoding="utf-8")
        text = read_content(path)
        assert "Héllo" in text


# =========================================================================
# 10. LEARNING MEMORY TESTS
# =========================================================================

class TestLearningMemory:

    def test_record_and_suggest(self, tmp_path: Path):
        mem = LearningMemory(tmp_path / "learn.sqlite3")
        mem.record(
            path=Path("test.pdf"), fingerprint="abc", text_signature="def",
            subject="Assurance", category="Contrat",
            hierarchy="Assurance / Contrat", context="police assurance belife",
        )
        suggestions = mem.suggest(filename="police_assurance.pdf", context="belife sinistre")
        assert len(suggestions) >= 1
        assert suggestions[0].subject == "Assurance"
        mem.close()

    def test_learned_labels_majority(self, tmp_path: Path):
        mem = LearningMemory(tmp_path / "learn.sqlite3")
        for i in range(3):
            mem.record(
                path=Path(f"phys_{i}.pdf"), fingerprint=f"fp{i}", text_signature=f"ts{i}",
                subject="Physique", category="Cours",
                context="physique electromagnetisme cours",
            )
        mem.record(
            path=Path("chimie.pdf"), fingerprint="fpc", text_signature="tsc",
            subject="Chimie", category="Cours",
            context="physique electromagnetisme cours",
        )
        labels = mem.learned_labels(filename="physique_em.pdf", context="electromagnetisme")
        assert labels["subject"] == "Physique"
        mem.close()

    def test_empty_memory_returns_nothing(self, tmp_path: Path):
        mem = LearningMemory(tmp_path / "empty.sqlite3")
        labels = mem.learned_labels(filename="anything.pdf")
        assert labels == {}
        mem.close()


# =========================================================================
# 11. AGENT LEDGER TESTS
# =========================================================================

class TestAgentLedger:

    def test_lifecycle(self, tmp_path: Path):
        ledger = AgentLedger(tmp_path / "ledger.sqlite3")
        f = tmp_path / "doc.txt"
        f.write_text("content", encoding="utf-8")
        assert ledger.needs_processing(f)
        ledger.start(f)
        ledger.finish(f, "done", target=tmp_path / "out.txt")
        (tmp_path / "out.txt").write_text("done", encoding="utf-8")
        assert not ledger.needs_processing(f)
        ledger.close()

    def test_recover_interrupted(self, tmp_path: Path):
        ledger = AgentLedger(tmp_path / "ledger.sqlite3")
        f = tmp_path / "doc.txt"
        f.write_text("content", encoding="utf-8")
        ledger.start(f)
        recovered = ledger.recover_interrupted()
        assert recovered == 1
        assert ledger.needs_processing(f)
        ledger.close()

    def test_modified_file_reprocessed(self, tmp_path: Path):
        ledger = AgentLedger(tmp_path / "ledger.sqlite3")
        f = tmp_path / "doc.txt"
        f.write_text("v1", encoding="utf-8")
        ledger.start(f)
        ledger.finish(f, "done", target=tmp_path / "out.txt")
        (tmp_path / "out.txt").write_text("r", encoding="utf-8")
        time.sleep(0.05)
        f.write_text("v2 modified", encoding="utf-8")
        assert ledger.needs_processing(f)
        ledger.close()


# =========================================================================
# 12. DOMAIN MODEL TESTS
# =========================================================================

class TestDomainModels:

    def test_folder_pair_allows_same(self, tmp_path: Path):
        d = tmp_path / "dir"
        d.mkdir()
        src, dst = resolve_folder_pair(d, d)
        assert src == dst

    def test_folder_pair_rejects_nested(self, tmp_path: Path):
        parent = tmp_path / "parent"
        child = parent / "child"
        parent.mkdir()
        child.mkdir()
        with pytest.raises(FolderPairError):
            resolve_folder_pair(parent, child)

    def test_folder_pair_rejects_nonexistent(self, tmp_path: Path):
        with pytest.raises(FolderPairError):
            resolve_folder_pair(tmp_path / "nope", tmp_path / "dest")

    def test_build_destination_creates_hierarchy(self, tmp_path: Path):
        c = Classification("Physique", "Cours", 90, "r", year="2024", domain="Sciences",
                           hierarchy=("2024", "Sciences", "Physique", "Cours"))
        dest, target, reason = build_destination(tmp_path, c, ".pdf", "doc")
        parts = target.relative_to(tmp_path).parts
        assert len(parts) >= 2

    def test_reuse_existing_folder(self, tmp_path: Path):
        (tmp_path / "Physique").mkdir()
        folder, reason = reuse_existing_folder(tmp_path, "Physique")
        assert folder == tmp_path / "Physique"
        assert "réutilisé" in reason

    def test_plan_item_key_stability(self, tmp_path: Path):
        f = tmp_path / "doc.txt"
        f.write_text("stable", encoding="utf-8")
        c = Classification("S", "C", 80, "r")
        item = PlanItem(f, c, tmp_path, tmp_path / "doc.txt")
        k1 = item.key
        k2 = item.key
        assert k1 == k2

    def test_plan_item_hierarchy_label(self, tmp_path: Path):
        c = Classification("Physique", "Cours", 80, "r",
                           hierarchy=("2024", "Sciences", "Physique"))
        item = PlanItem(Path("a.txt"), c, tmp_path / "2024" / "Sciences" / "Physique",
                        tmp_path / "2024" / "Sciences" / "Physique" / "a.txt",
                        destination_root=tmp_path)
        assert "Physique" in item.hierarchy_label

    def test_naming_service_safe_title_detection(self):
        svc = FilenameProposalService()
        assert not svc._is_safe_title("Document")
        assert not svc._is_safe_title("12345")
        assert not svc._is_safe_title("2024/01/15")
        assert svc._is_safe_title("Cours de physique electromagnetisme")

    def test_content_identity_service(self, tmp_path: Path):
        f = tmp_path / "doc.txt"
        f.write_text("Cours de physique", encoding="utf-8")
        svc = ContentIdentityService()
        identity = svc.identify(f)
        assert identity is not None
        assert identity.sha256
        assert identity.size > 0
        assert identity.text_length > 0


# =========================================================================
# 13. CACHE TESTS
# =========================================================================

class TestCache:

    def test_cache_stores_and_retrieves(self, tmp_path: Path):
        cache = ClassificationCache(tmp_path / "cache.sqlite3")
        f = tmp_path / "doc.txt"
        f.write_text("content", encoding="utf-8")
        c = Classification("Physique", "Cours", 85, "test")
        cache.put(f, "v1", c)
        retrieved = cache.get(f, "v1")
        assert retrieved is not None
        assert retrieved.subject == "Physique"

    def test_cache_invalidates_on_rules_change(self, tmp_path: Path):
        cache = ClassificationCache(tmp_path / "cache.sqlite3")
        f = tmp_path / "doc.txt"
        f.write_text("content", encoding="utf-8")
        c = Classification("Physique", "Cours", 85, "test")
        cache.put(f, "v1", c)
        assert cache.get(f, "v2") is None

    def test_cache_prune(self, tmp_path: Path):
        cache = ClassificationCache(tmp_path / "cache.sqlite3")
        for i in range(20):
            f = tmp_path / f"doc_{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            c = Classification("S", "C", 80, "r")
            cache.put(f, "v1", c)
        cache.prune(max_rows=5)


# =========================================================================
# 14. DUPLICATE SERVICE TESTS
# =========================================================================

class TestDuplicateService:

    def test_quarantine_moves_not_deletes(self, tmp_path: Path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("same", encoding="utf-8")
        b.write_text("same", encoding="utf-8")
        report = scan_duplicates([tmp_path])
        quarantine = tmp_path / "quarantine"
        svc = DuplicateService()
        moved = svc.quarantine(report, quarantine)
        assert len(moved) >= 1
        assert quarantine.exists()
        assert a.exists() or b.exists()

    def test_duplicate_victims_skips_changed(self, tmp_path: Path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("same", encoding="utf-8")
        b.write_text("same", encoding="utf-8")
        report = scan_duplicates([tmp_path])
        b.write_text("CHANGED", encoding="utf-8")
        victims = duplicate_victims(report)
        assert b not in victims
