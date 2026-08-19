import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from mdjr_classeur.app import SearchDialog
from mdjr_classeur.classifier import LocalClassifier
from mdjr_classeur.search_index import SearchIndex


app = QApplication.instance() or QApplication([])
root = Path("/tmp/mdjr-search-smoke")
root.mkdir(parents=True, exist_ok=True)
document = root / "cours_maths.txt"
document.write_text("Integrales et primitives", encoding="utf-8")
index = SearchIndex(root / "search.sqlite3")
index.upsert(document, LocalClassifier().classify(document), "classé")
dialog = SearchDialog(index)
dialog.refresh_results()
assert dialog.table.rowCount() == 1
dialog.close()
index.close()
print("search gui smoke ok")
