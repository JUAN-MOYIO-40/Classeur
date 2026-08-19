import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
from PySide6.QtWidgets import QApplication

from mdjr_classeur.app import HierarchyDialog, MainWindow, PlanItem, build_destination
from mdjr_classeur.classifier import LocalClassifier

app = QApplication([])
window = MainWindow()
assert window.windowTitle().startswith("MDJR classeur")
assert window.model.rowCount() == 0
with TemporaryDirectory() as folder:
    source = Path(folder) / "L1_physique_electromagnetisme_cours.txt"
    source.write_text("Année 1\nCours de physique et électromagnétisme", encoding="utf-8")
    classification = LocalClassifier().classify(source)
    destination_dir, destination_file, reason = build_destination(Path(folder) / "Classement", classification, source.suffix, source.stem)
    item = PlanItem(source, classification, destination_dir, destination_file, destination_reason=reason, destination_root=Path(folder) / "Classement")
    hierarchy_dialog = HierarchyDialog([item], window)
    assert hierarchy_dialog.tree.topLevelItemCount() == 1
    hierarchy_dialog.close()
window.close()
app.quit()
print("GUI_SMOKE_OK")
