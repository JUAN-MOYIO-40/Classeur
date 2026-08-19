from pathlib import Path
from tempfile import TemporaryDirectory
from mdjr_classeur.classifier import LocalClassifier
from mdjr_classeur.search_index import SearchIndex

with TemporaryDirectory() as folder:
    root = Path(folder)
    document = root / "L1_physique_electromagnetisme_cours.txt"
    document.write_text("Année 1\nIntégrales de physique : électromagnétisme", encoding="utf-8")
    classification = LocalClassifier().classify(document)
    print(classification)
    index = SearchIndex(root / "search.sqlite3")
    index.upsert(document, classification, "classé")
    for query in ("annee 1", "sciences", "physique", "electromagnetisme"):
        print(query, index.search(query))
    index.close()
