import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication

from mdjr_classeur.app import MainWindow

app = QApplication([])
with TemporaryDirectory() as root:
    root = Path(root)
    source = root / "a_trier"
    destination = root / "classement"
    source.mkdir()
    window = MainWindow()
    window.source_edit.setText(str(source))
    window.destination_edit.setText(str(destination))
    window.watching = True
    window.auto_checkbox.setChecked(True)

    new_file = source / "cours_informatique_python.txt"
    new_file.write_text("Cours d'informatique : Python et algorithmique", encoding="utf-8")

    window.poll_folder()  # première observation : le fichier doit être stabilisé
    assert not list(destination.rglob("*"))
    window.poll_folder()  # deuxième observation : le classement peut démarrer
    if window.apply_thread:
        window.apply_thread.wait(10000)
    app.processEvents()
    targets = [path for path in destination.rglob("*.txt") if "Python" in path.name]
    assert targets, "Le nouveau fichier n’a pas été classé automatiquement"
    assert new_file.exists(), "Le mode copie doit préserver l’original"
    window.close()
app.quit()
print("REALTIME_SIMULATION_OK")
