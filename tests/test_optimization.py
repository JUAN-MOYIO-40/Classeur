from pathlib import Path

from mdjr_classeur.cache import ClassificationCache
from mdjr_classeur.classifier import LocalClassifier


def test_cache_reutilise_une_classification_inchangee(tmp_path: Path):
    document = tmp_path / "document.txt"
    document.write_text("Cours de mathematiques sur les integrales", encoding="utf-8")
    cache = ClassificationCache(tmp_path / "cache.sqlite3")
    classifier = LocalClassifier()
    first = classifier.classify(document)
    cache.put(document, classifier.rules_version, first)
    second = cache.get(document, classifier.rules_version)
    assert second is not None
    assert second.subject == first.subject
    assert second.title == first.title


def test_version_des_regles_invalide_le_cache(tmp_path: Path):
    document = tmp_path / "document.txt"
    document.write_text("Cours de mathematiques", encoding="utf-8")
    cache = ClassificationCache(tmp_path / "cache.sqlite3")
    classifier = LocalClassifier()
    cache.put(document, classifier.rules_version, classifier.classify(document))
    classifier.categories["Cours"].append("support pedagogique")
    assert cache.get(document, classifier.rules_version) is None


def test_moteur_reconnait_une_variation_proche(tmp_path: Path):
    document = tmp_path / "support.txt"
    document.write_text("mathematiques et integrale", encoding="utf-8")
    result = LocalClassifier().classify(document)
    assert result.subject == "Mathématiques"
