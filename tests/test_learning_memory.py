from pathlib import Path

from mdjr_classeur.application.learning import LearningMemory


def test_correction_is_reused_as_learned_label(tmp_path: Path):
    memory = LearningMemory(tmp_path / "learning.sqlite3")
    try:
        source = tmp_path / "cours_physique.pdf"
        source.write_text("", encoding="utf-8")
        memory.record(
            path=source,
            fingerprint="abc",
            text_signature="text",
            subject="Physique",
            category="Cours",
            hierarchy="Université / Physique",
            context="électromagnétisme électrostatique",
        )
        labels = memory.learned_labels(filename="nouveau_cours_physique.pdf", context="électromagnétisme")
        assert labels["subject"] == "Physique"
        assert labels["category"] == "Cours"
    finally:
        memory.close()


def test_empty_memory_has_no_hallucinated_label(tmp_path: Path):
    memory = LearningMemory(tmp_path / "learning.sqlite3")
    try:
        assert memory.learned_labels(filename="document_inconnu.txt") == {}
    finally:
        memory.close()
