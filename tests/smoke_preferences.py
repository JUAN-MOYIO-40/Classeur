from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication

import mdjr_classeur.app as app_module
from mdjr_classeur.preferences import save_preferences


with TemporaryDirectory() as root_dir:
    root = Path(root_dir)
    app_module.CONFIG_DIR = root
    app_module.CONFIG_FILE = root / "config.json"
    app_module.LOG_FILE = root / "historique.json"
    app_module.CACHE_FILE = root / "classifications.sqlite3"
    app_module.SEARCH_INDEX_FILE = root / "search.sqlite3"
    app_module.PREFERENCES_FILE = root / "preferences.json"
    save_preferences(app_module.PREFERENCES_FILE, {"language": "en", "theme": "dark", "accent": "#336699", "background": "", "confirm_actions": True})
    qt_app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    assert window.preferences["theme"] == "dark"
    assert window.windowTitle().startswith("MDJR Classeur")
    assert window.preferences_button.text() == "Preferences"
    assert window.history_button.text() == "History"
    window.close()
    qt_app.quit()

print("PREFERENCES_GUI_SMOKE_OK")
