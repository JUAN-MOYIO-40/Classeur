from pathlib import Path

from mdjr_classeur.classifier import LocalClassifier
from mdjr_classeur.search_index import SearchIndex


def test_search_finds_content_and_status(tmp_path: Path):
    database = tmp_path / "search.sqlite3"
    document = tmp_path / "L1_physique_electromagnetisme_cours.txt"
    document.write_text("Année 1\nIntégrales de physique : électromagnétisme", encoding="utf-8")
    classifier = LocalClassifier()
    index = SearchIndex(database)
    classification = classifier.classify(document)
    index.upsert(document, classification, "classé")

    records = index.search("integrales")
    assert len(records) == 1
    assert records[0].path == str(document.resolve())
    assert index.search("annee 1")
    assert index.search("sciences")
    assert index.search("physique")
    assert index.search("electromagnetisme")
    assert index.search("integrales", "en attente") == []
    index.close()


def test_search_updates_and_deletes_entry(tmp_path: Path):
    database = tmp_path / "search.sqlite3"
    document = tmp_path / "attestation.txt"
    document.write_text("Attestation de scolarité", encoding="utf-8")
    classifier = LocalClassifier()
    index = SearchIndex(database)
    index.upsert(document, classifier.classify(document), "en attente")
    assert len(index.search("scolarite")) == 1

    index.delete_path(document)
    assert index.search("scolarite") == []
    index.close()
