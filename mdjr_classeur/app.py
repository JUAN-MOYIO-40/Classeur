from __future__ import annotations

import json
import queue
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPalette

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter,
    QStatusBar, QTableView, QTextEdit, QVBoxLayout, QWidget, QDialog,
    QSystemTrayIcon,
)

from .cache import ClassificationCache
from .classifier import LocalClassifier
from .dedupe import DuplicateReport, delete_duplicates, format_bytes, quarantine_duplicates, scan_duplicates
from .search_index import SearchIndex, SearchRecord
from .i18n import set_language, tr
from .preferences import load_preferences, save_preferences
from .domain.models import PlanItem
from .domain.paths import FolderPairError, resolve_folder_pair
from .domain.planning import build_destination
from .application.services import ClassificationService, ScanService, UndoService
from .application.indexing import SearchIndexService
from .application.duplicates import DuplicateService
from .application.plan import PlanEditService
from .infrastructure.filesystem import FileOperationService, atomic_write_text, is_ignored_file
from .infrastructure.history import HistoryRepository
from .infrastructure.watcher import Observer, WatchEventHandler
from .presentation.dialogs import (
    DuplicateDialog, HierarchyDialog, HistoryDialog, PreferencesDialog, RulesDialog, SearchDialog,
)
from .presentation.models import PlanModel
from .presentation.workers import ApplyWorker, DuplicateWorker, ScanWorker, SearchIndexWorker

APP_NAME = "MDJR classeur"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


CONFIG_DIR = Path.home() / ".mdjr_classeur"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "historique.json"
CACHE_FILE = CONFIG_DIR / "classifications.sqlite3"
SEARCH_INDEX_FILE = CONFIG_DIR / "search.sqlite3"
PREFERENCES_FILE = CONFIG_DIR / "preferences.json"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.preferences = load_preferences(PREFERENCES_FILE)
        set_language(str(self.preferences.get("language", "fr")))
        self.setWindowTitle(tr("MDJR classeur") + " - " + tr("votre assistant documentaire local"))
        self.setWindowIcon(QIcon(str(resource_path("assets/mdjr.svg"))))
        self.resize(1320, 820)
        self.classifier = LocalClassifier.from_json(CONFIG_DIR / "regles.json")
        self.cache = ClassificationCache(CACHE_FILE)
        self.search_index = SearchIndex(SEARCH_INDEX_FILE)
        self.classification_service = ClassificationService(self.classifier, self.cache)
        self.scan_service = ScanService(self.classification_service)
        self.history_repository = HistoryRepository(LOG_FILE)
        self.undo_service = UndoService(self.history_repository)
        self.file_operation_service = FileOperationService()
        self.duplicate_service = DuplicateService()
        self.plan_edit_service = PlanEditService()
        self.search_worker = None
        self.search_dialog = None
        self.model = PlanModel(self.plan_edit_service)
        self.scan_thread = None
        self.apply_thread = None
        self.known_keys: set[str] = set()
        self.pending_signatures: dict[str, str] = {}
        self.event_queue = queue.Queue()
        self.watch_observer = None
        self.auto_mode = False
        self.watching = False
        self._build_ui()
        self._load_config()
        self._setup_tray()
        self.apply_preferences()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_folder)
        self.timer.start(2500)

    def _build_ui(self):
        self.setStyleSheet("""
            QMainWindow { background: #f4f7fb; }
            QLabel { color: #18324b; }
            QFrame#hero { background: #17324d; border-radius: 18px; }
            QFrame#hero QLabel { color: white; }
            QFrame#statCard { background: white; border: 1px solid #dce5ef; border-radius: 12px; }
            QLabel#statValue { color: #17324d; font-size: 22px; font-weight: 800; }
            QLabel#statCaption { color: #6a8298; font-size: 12px; }
            QLabel#title { font-size: 30px; font-weight: 800; }
            QLabel#subtitle { color: #b8cbe0; font-size: 14px; }
            QLineEdit, QTextEdit, QComboBox, QSpinBox { background: white; border: 1px solid #d8e1ec; border-radius: 8px; padding: 8px; }
            QPushButton { background: #1c8c70; color: white; border: none; border-radius: 8px; padding: 10px 16px; font-weight: 700; }
            QPushButton:hover { background: #15735d; }
            QPushButton#secondary { background: #e5edf5; color: #23415d; }
            QPushButton#danger { background: #fff0ee; color: #b43d36; }
            QTableView { background: white; border: 1px solid #dce5ef; border-radius: 12px; gridline-color: #edf1f5; selection-background-color: #dcefe9; selection-color: #17324d; }
            QHeaderView::section { background: #edf3f8; color: #47627a; padding: 10px; border: none; font-weight: 700; }
            QCheckBox { color: #23415d; padding: 6px; }
            QProgressBar { border: none; background: #e4edf4; border-radius: 5px; height: 9px; text-align: center; }
            QProgressBar::chunk { background: #1c8c70; border-radius: 5px; }
        """)
        central = QWidget()
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)

        hero = QFrame(objectName="hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(26, 22, 26, 22)
        title_box = QVBoxLayout()
        title = QLabel(tr("MDJR classeur"), objectName="title")
        subtitle = QLabel(tr("Le classeur intelligent qui comprend vos documents - en local, avec contrôle total."), objectName="subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hero_layout.addLayout(title_box)
        hero_layout.addStretch()
        self.status_badge = QLabel("●  " + tr("Surveillance inactive"))
        self.status_badge.setStyleSheet("color: #ffcf66; font-weight: 700; font-size: 14px;")
        hero_layout.addWidget(self.status_badge, alignment=Qt.AlignVCenter)
        root.addWidget(hero)

        paths = QFrame()
        paths_layout = QVBoxLayout(paths)
        paths_layout.setContentsMargins(0, 0, 0, 0)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel(tr("Dossier à surveiller")))
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText(tr("Choisis le dossier où arrivent les fichiers…"))
        source_row.addWidget(self.source_edit, 1)
        source_button = QPushButton(tr("Parcourir"))
        source_button.setObjectName("secondary")
        source_button.clicked.connect(self.choose_source)
        source_row.addWidget(source_button)
        paths_layout.addLayout(source_row)
        destination_row = QHBoxLayout()
        destination_row.addWidget(QLabel(tr("Dossier de classement")))
        self.destination_edit = QLineEdit()
        self.destination_edit.setPlaceholderText(tr("Choisis le dossier qui contiendra l’organisation finale…"))
        destination_row.addWidget(self.destination_edit, 1)
        destination_button = QPushButton(tr("Parcourir"))
        destination_button.setObjectName("secondary")
        destination_button.clicked.connect(self.choose_destination)
        destination_row.addWidget(destination_button)
        paths_layout.addLayout(destination_row)
        root.addWidget(paths)

        stats_row = QHBoxLayout()
        def stat_card(caption: str):
            card = QFrame(objectName="statCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 10, 16, 10)
            value = QLabel("0", objectName="statValue")
            label = QLabel(caption, objectName="statCaption")
            card_layout.addWidget(value)
            card_layout.addWidget(label)
            stats_row.addWidget(card, 1)
            return value
        self.pending_stat = stat_card(tr("fichiers en attente"))
        self.reuse_stat = stat_card(tr("destinations réutilisées"))
        self.confidence_stat = stat_card(tr("confiance moyenne"))
        root.addLayout(stats_row)

        actions = QHBoxLayout()
        self.scan_button = QPushButton(tr("Analyser les fichiers existants"))
        self.scan_button.clicked.connect(self.scan_existing)
        actions.addWidget(self.scan_button)
        self.watch_button = QPushButton(tr("Démarrer la surveillance"))
        self.watch_button.clicked.connect(self.toggle_watch)
        actions.addWidget(self.watch_button)
        self.approve_button = QPushButton(tr("Classer les éléments sélectionnés"))
        self.approve_button.clicked.connect(self.apply_selected)
        actions.addWidget(self.approve_button)
        self.clear_button = QPushButton(tr("Vider la file"))
        self.clear_button.setObjectName("danger")
        self.clear_button.clicked.connect(self.clear_queue)
        actions.addWidget(self.clear_button)
        self.undo_button = QPushButton(tr("Annuler la dernière opération"))
        self.undo_button.setObjectName("secondary")
        self.undo_button.clicked.connect(self.undo_last)
        actions.addWidget(self.undo_button)
        self.history_button = QPushButton(tr("Historique"))
        self.history_button.setObjectName("secondary")
        self.history_button.clicked.connect(self.open_history)
        actions.addWidget(self.history_button)
        self.duplicate_button = QPushButton(tr("Scanner les doublons"))
        self.duplicate_button.setObjectName("secondary")
        self.duplicate_button.clicked.connect(self.open_duplicate_scan)
        actions.addWidget(self.duplicate_button)
        self.hierarchy_button = QPushButton(tr("Aperçu arborescence"))
        self.hierarchy_button.setObjectName("secondary")
        self.hierarchy_button.clicked.connect(self.open_hierarchy_preview)
        actions.addWidget(self.hierarchy_button)
        self.search_button = QPushButton(tr("Recherche rapide"))
        self.search_button.setObjectName("secondary")
        self.search_button.clicked.connect(self.open_search)
        actions.addWidget(self.search_button)
        actions.addStretch()
        self.rules_button = QPushButton(tr("Règles"))
        self.rules_button.setObjectName("secondary")
        self.rules_button.clicked.connect(self.open_rules)
        actions.addWidget(self.rules_button)
        self.preferences_button = QPushButton(tr("Préférences"))
        self.preferences_button.setObjectName("secondary")
        self.preferences_button.clicked.connect(self.open_preferences)
        actions.addWidget(self.preferences_button)
        root.addLayout(actions)

        settings_row = QHBoxLayout()
        self.auto_checkbox = QCheckBox(tr("Autoriser le classement automatique pendant la surveillance (les cas ambigus vont dans À trier)"))
        self.auto_checkbox.stateChanged.connect(self.set_auto_mode)
        settings_row.addWidget(self.auto_checkbox)
        settings_row.addStretch()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(tr("Copier l’original (recommandé)"), "copy")
        self.mode_combo.addItem(tr("Déplacer l’original"), "move")
        settings_row.addWidget(QLabel(tr("Action :")))
        settings_row.addWidget(self.mode_combo)
        root.addLayout(settings_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        splitter = QSplitter(Qt.Vertical)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        splitter.addWidget(self.table)
        self.explain = QTextEdit()
        self.explain.setReadOnly(True)
        self.explain.setPlaceholderText("Sélectionne un fichier pour voir la logique de classement et un aperçu du contenu analysé.")
        self.table.selectionModel().selectionChanged.connect(self.show_explanation)
        splitter.addWidget(self.explain)
        splitter.setSizes([570, 120])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(tr("Choisis un dossier à surveiller pour commencer."))
        self.update_stats()

    def apply_preferences(self):
        app = QApplication.instance()
        theme = str(self.preferences.get("theme", "system"))
        accent = QColor(str(self.preferences.get("accent", "#1c8c70")))
        if not accent.isValid():
            accent = QColor("#1c8c70")
        if theme == "dark":
            window, surface, field, text, muted, border = "#17202a", "#202c38", "#263746", "#edf4f8", "#a9bdc9", "#3b5263"
            if app:
                palette = QPalette()
                palette.setColor(QPalette.Window, QColor(window))
                palette.setColor(QPalette.Base, QColor(field))
                palette.setColor(QPalette.Text, QColor(text))
                palette.setColor(QPalette.Button, QColor(surface))
                palette.setColor(QPalette.ButtonText, QColor(text))
                app.setPalette(palette)
        elif theme == "light":
            window, surface, field, text, muted, border = "#f4f7fb", "#ffffff", "#ffffff", "#18324b", "#6a8298", "#d8e1ec"
            if app:
                app.setPalette(app.style().standardPalette())
        else:
            palette = app.style().standardPalette() if app else QPalette()
            window = palette.color(QPalette.Window).name()
            surface = palette.color(QPalette.Base).name()
            field = palette.color(QPalette.Base).name()
            text = palette.color(QPalette.Text).name()
            muted = palette.color(QPalette.PlaceholderText).name()
            border = palette.color(QPalette.Mid).name()
            if app:
                app.setPalette(palette)
        hover = accent.darker(115).name()
        background = str(self.preferences.get("background", ""))
        image_rule = ""
        if background and Path(background).expanduser().is_file():
            image_rule = f'background-image: url("{Path(background).expanduser().as_posix()}"); background-position: center; background-repeat: no-repeat;'
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {window}; }}
            QWidget#central {{ background-color: {window}; {image_rule} }}
            QLabel {{ color: {text}; }}
            QFrame#hero {{ background: {accent.name()}; border-radius: 18px; }}
            QFrame#hero QLabel {{ color: white; }}
            QFrame#statCard {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
            QLabel#statValue {{ color: {text}; font-size: 22px; font-weight: 800; }}
            QLabel#statCaption {{ color: {muted}; font-size: 12px; }}
            QLabel#title {{ font-size: 30px; font-weight: 800; }}
            QLabel#subtitle {{ color: #d5e6f0; font-size: 14px; }}
            QLineEdit, QTextEdit, QComboBox, QSpinBox {{ background: {field}; color: {text}; border: 1px solid {border}; border-radius: 8px; padding: 8px; }}
            QPushButton {{ background: {accent.name()}; color: white; border: none; border-radius: 8px; padding: 10px 16px; font-weight: 700; }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton#secondary {{ background: {surface}; color: {text}; border: 1px solid {border}; }}
            QPushButton#danger {{ background: #fff0ee; color: #b43d36; }}
            QTableView {{ background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 12px; gridline-color: {border}; selection-background-color: {accent.name()}; selection-color: white; }}
            QHeaderView::section {{ background: {surface}; color: {muted}; padding: 10px; border: none; font-weight: 700; }}
            QCheckBox {{ color: {text}; padding: 6px; }}
            QProgressBar {{ border: none; background: {border}; border-radius: 5px; height: 9px; text-align: center; }}
            QProgressBar::chunk {{ background: {accent.name()}; border-radius: 5px; }}
        """)

    def open_preferences(self):
        dialog = PreferencesDialog(self.preferences, self)
        if dialog.exec() != QDialog.Accepted:
            return
        old_language = str(self.preferences.get("language", "fr"))
        self.preferences = dialog.values()
        save_preferences(PREFERENCES_FILE, self.preferences)
        set_language(str(self.preferences.get("language", "fr")))
        self.apply_preferences()
        self.setWindowTitle(tr("MDJR classeur") + " - " + tr("votre assistant documentaire local"))
        if old_language != str(self.preferences.get("language", "fr")):
            QMessageBox.information(self, tr("Préférences de Classeur"), tr("Les changements de langue seront appliqués au prochain démarrage."))

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(str(resource_path("assets/mdjr.svg"))))
        self.tray.setToolTip(APP_NAME)
        menu = self.tray.contextMenu() if self.tray.contextMenu() else None
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        show_action = QAction("Ouvrir MDJR classeur", self)
        show_action.triggered.connect(self.showNormal)
        menu.addAction(show_action)
        quit_action = QAction("Quitter", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _load_config(self):
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
            self.source_edit.setText(data.get("source", ""))
            self.destination_edit.setText(data.get("destination", ""))
        except (OSError, json.JSONDecodeError):
            pass

    def _save_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_text(CONFIG_FILE, json.dumps({"version": 2, "source": self.source_edit.text(), "destination": self.destination_edit.text()}, ensure_ascii=False, indent=2))
        self.classifier.save_json(CONFIG_DIR / "regles.json")

    def choose_source(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choisir le dossier à surveiller")
        if chosen:
            self.source_edit.setText(chosen)
            if not self.destination_edit.text():
                self.destination_edit.setText(str(Path(chosen).parent / "MDJR_Classement"))
            self._save_config()

    def choose_destination(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choisir le dossier de classement")
        if chosen:
            self.destination_edit.setText(chosen)
            self._save_config()

    def folder_paths(self) -> tuple[Path, Path] | None:
        source_text = self.source_edit.text().strip()
        destination_text = self.destination_edit.text().strip()
        if not source_text or not destination_text:
            QMessageBox.warning(self, "Dossiers requis", "Choisis un dossier à surveiller et un dossier de classement.")
            return None
        try:
            source, destination = resolve_folder_pair(Path(source_text), Path(destination_text))
        except FolderPairError as exc:
            QMessageBox.warning(self, "Configuration invalide", str(exc))
            return None
        self._save_config()
        return source, destination

    def scan_existing(self):
        paths = self.folder_paths()
        if not paths or (self.scan_thread and self.scan_thread.isRunning()):
            return
        source, destination = paths
        self.scan_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage("Analyse du dossier et du contenu des fichiers en cours…")
        self.scan_thread = ScanWorker(source, destination, self.classifier, self.cache, self.scan_service)
        self.scan_thread.completed.connect(self.on_scan_completed)
        self.scan_thread.failed.connect(self.on_worker_failed)
        self.scan_thread.start()

    def on_scan_completed(self, items, count):
        self.scan_button.setEnabled(True)
        self.progress.setVisible(False)
        added = self.model.add_items(items)
        for item in items:
            self.search_index.upsert_plan_item(item, "en attente")
        self.known_keys.update(item.key for item in items)
        self.statusBar().showMessage(f"Analyse terminée : {count} fichier(s) détecté(s), {added} proposition(s) ajoutée(s).")
        self.update_badge()
        if self.auto_checkbox.isChecked() and items:
            self.execute_items(items)
        if added and self.tray.isVisible():
            self.tray.showMessage(APP_NAME, f"{added} fichier(s) prêt(s) à être classé(s).", QSystemTrayIcon.Information, 5000)

    def _start_watch_observer(self, source: Path):
        if Observer is None:
            self.statusBar().showMessage("Surveillance légère active (mode polling de secours).")
            return
        try:
            self.watch_observer = Observer()
            self.watch_observer.schedule(WatchEventHandler(self.event_queue), str(source), recursive=True)
            self.watch_observer.start()
            self.statusBar().showMessage("Surveillance événementielle active : aucune analyse inutile au repos.")
        except OSError:
            self.watch_observer = None
            self.statusBar().showMessage("Surveillance légère active (mode polling de secours).")

    def _stop_watch_observer(self):
        observer = self.watch_observer
        self.watch_observer = None
        if observer is not None:
            observer.stop()
            observer.join(timeout=2)

    def _event_candidates(self, source: Path, destination: Path) -> set[Path]:
        candidates: set[Path] = set()
        if self.watch_observer is None:
            try:
                candidates.update(path for path in source.rglob("*") if path.is_file())
            except OSError:
                return candidates
        else:
            while True:
                try:
                    candidates.add(self.event_queue.get_nowait())
                except queue.Empty:
                    break
            candidates.update(Path(path) for path in self.pending_signatures if Path(path).exists())
        valid = set()
        for path in candidates:
            try:
                if not path.is_file() or path.is_symlink() or is_ignored_file(path):
                    continue
                path.relative_to(destination)
                continue
            except (OSError, ValueError):
                pass
            valid.add(path)
        return valid

    def poll_folder(self):
        if not self.watching:
            return
        source = Path(self.source_edit.text().strip()).expanduser()
        destination = Path(self.destination_edit.text().strip()).expanduser()
        if not source.exists() or not destination:
            return
        fresh = []
        try:
            for path in self._event_candidates(source, destination):
                key = self.file_key(path)
                path_id = str(path.resolve())
                if key not in self.known_keys:
                    # Deux observations identiques garantissent que la copie est terminée.
                    previous_key = self.pending_signatures.get(path_id)
                    if previous_key != key:
                        self.pending_signatures[path_id] = key
                        continue
                    item = self.scan_service.analyze_path(path, destination, existing=False)
                    if item is None:
                        continue
                    fresh.append(item)
                    self.search_index.upsert_plan_item(item, "en attente")
                    self.known_keys.add(key)
                    self.pending_signatures.pop(path_id, None)
            if fresh:
                added = self.model.add_items(fresh)
                self.statusBar().showMessage(f"{added} nouveau(x) fichier(s) détecté(s).")
                self.update_badge()
                if self.auto_checkbox.isChecked():
                    self.execute_items(fresh)
                if self.tray.isVisible():
                    self.tray.showMessage(APP_NAME, f"{len(fresh)} nouveau(x) fichier(s) détecté(s).", QSystemTrayIcon.Information, 4500)
        except OSError:
            pass

    @staticmethod
    def file_key(path: Path) -> str:
        try:
            stat = path.stat()
            return f"{path.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"
        except OSError:
            return str(path.resolve())

    def toggle_watch(self):
        if self.watch_button.text() == "Démarrer la surveillance":
            if not self.folder_paths():
                self.watching = False
                return
            if bool(self.preferences.get("confirm_actions", True)):
                permission = QMessageBox.question(
                    self,
                    "Autoriser la surveillance automatique ?",
                    "MDJR classeur va analyser les fichiers déjà présents puis classer automatiquement les nouveaux fichiers pendant que la surveillance est active.\n\nLes fichiers ambigus seront placés dans « À trier / Autre ». Aucun fichier ne sera supprimé. Autoriser cette session ?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if permission != QMessageBox.Yes:
                    return
            self.auto_checkbox.setChecked(True)
            self.watching = True
            source = Path(self.source_edit.text().strip()).expanduser()
            self._start_watch_observer(source)
            self.watch_button.setText("Arrêter la surveillance")
            self.watch_button.setObjectName("danger")
            self.watch_button.style().unpolish(self.watch_button)
            self.watch_button.style().polish(self.watch_button)
            self.status_badge.setText("●  Surveillance active")
            self.status_badge.setStyleSheet("color: #8ff0c6; font-weight: 700; font-size: 14px;")
            self.statusBar().showMessage("Surveillance active : les nouveaux fichiers seront détectés localement.")
            self.scan_existing()
        else:
            self.watching = False
            self._stop_watch_observer()
            self.event_queue = queue.Queue()
            self.pending_signatures.clear()
            self.watch_button.setText("Démarrer la surveillance")
            self.status_badge.setText("●  Surveillance inactive")
            self.status_badge.setStyleSheet("color: #ffcf66; font-weight: 700; font-size: 14px;")
            self.statusBar().showMessage("Surveillance arrêtée.")

    def _search_roots(self) -> list[Path]:
        roots: list[Path] = []
        for value in (self.source_edit.text().strip(), self.destination_edit.text().strip()):
            if not value:
                continue
            path = Path(value).expanduser()
            if path.exists() and path.is_dir():
                resolved = path.resolve()
                if resolved not in roots:
                    roots.append(resolved)
        return roots

    def refresh_search_index(self):
        if self.search_worker and self.search_worker.isRunning():
            return
        roots = self._search_roots()
        if not roots:
            return
        self.search_worker = SearchIndexWorker(roots, self.search_index, self.classifier, self.cache, list(self.model.items))
        self.search_worker.completed.connect(self.on_search_index_completed)
        self.search_worker.failed.connect(self.on_search_index_failed)
        self.search_worker.start()

    def on_search_index_completed(self, count: int):
        if self.search_dialog:
            self.search_dialog.refresh_results()
        self.statusBar().showMessage(f"Index de recherche local actualisé : {count} élément(s) vérifié(s).")

    def on_search_index_failed(self, message: str):
        if self.search_dialog:
            self.search_dialog.summary.setText(f"Index partiellement disponible : {message}")

    def open_hierarchy_preview(self):
        if not self.model.items:
            QMessageBox.information(self, "Arborescence vide", "Analyse d’abord les fichiers existants ou démarre la surveillance pour obtenir des propositions.")
            return
        dialog = HierarchyDialog(self.model.items, self)
        dialog.exec()

    def open_search(self):
        if not self._search_roots() and not self.model.items:
            QMessageBox.information(self, "Dossiers requis", "Choisis au moins un dossier avant d’utiliser la recherche rapide.")
            return
        self.search_dialog = SearchDialog(self.search_index, self)
        self.search_dialog.refresh_results()
        self.refresh_search_index()
        self.search_dialog.exec()
        self.search_dialog = None

    def update_stats(self):
        items = self.model.items
        self.pending_stat.setText(str(len(items)))
        reused = sum("réutilisé" in item.destination_reason or "rapproché" in item.destination_reason for item in items)
        self.reuse_stat.setText(str(reused))
        average = round(sum(item.confidence for item in items) / len(items)) if items else 0
        self.confidence_stat.setText(f"{average} %")

    def update_badge(self):
        pending = len(self.model.items)
        self.update_stats()
        if pending:
            self.status_badge.setText(f"●  {pending} fichier(s) en attente")
        elif self.watching:
            self.status_badge.setText("●  Surveillance active")
        else:
            self.status_badge.setText("●  Surveillance inactive")

    def show_explanation(self, selected, deselected):
        rows = selected.indexes()
        if not rows:
            return
        item = self.model.items[rows[0].row()]
        preview = item.classification.extracted_preview or "Aucun extrait textuel disponible pour ce format."
        content_status = item.classification.content_status or "état d’extraction non disponible (ancienne classification)"
        proposed = item.suggested_name or item.destination_file.stem or item.source.stem
        identity = item.sha256[:16] + "…" if item.sha256 else "indisponible"
        self.explain.setPlainText(f"Pourquoi cette proposition ?\n{item.classification.reason}\n\nNom original : {item.source.name}\nNom proposé : {proposed}{item.source.suffix}\nConfiance du nom : {item.rename_confidence} %\nJustification du nom : {item.rename_reason or 'nom d’origine conservé'}\n\nQualité de lecture : {content_status}\nIdentité SHA-256 : {identity}\n\nAperçu local du contenu :\n{preview}\n\nDestination :\n{item.destination_file}\n\nArborescence : {item.destination_reason or 'création ou réutilisation déterminée pendant l’analyse.'}")

    def set_auto_mode(self, state):
        self.auto_mode = state == Qt.Checked
        if self.auto_mode:
            self.statusBar().showMessage("Classement automatique local activé pour la session de surveillance ; les cas ambigus restent traçables dans À trier.")

    def apply_selected(self):
        items = self.model.selected_items()
        if not items:
            QMessageBox.information(self, "Aucun élément", "Sélectionne au moins un fichier dans la colonne de gauche.")
            return
        low = sum(item.confidence < 50 for item in items)
        message = f"MDJR va préparer {len(items)} classement(s)."
        if low:
            message += f"\n\n{low} proposition(s) ont une confiance faible et méritent une vérification."
        message += "\n\nLes dossiers nécessaires seront créés et les fichiers seront renommés selon les propositions affichées."
        if bool(self.preferences.get("confirm_actions", True)) and QMessageBox.question(self, "Autoriser le classement", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.execute_items(items)

    def execute_items(self, items):
        if self.apply_thread and self.apply_thread.isRunning():
            return
        mode = self.mode_combo.currentData() or "copy"
        self.approve_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.apply_thread = ApplyWorker(items, mode, self.file_operation_service)
        self.apply_thread.progress.connect(lambda value, name: (self.progress.setValue(value), self.statusBar().showMessage(f"Classement : {name}")))
        self.apply_thread.completed.connect(self.on_apply_completed)
        self.apply_thread.failed.connect(self.on_worker_failed)
        self.apply_thread.start()

    def on_apply_completed(self, results):
        self.approve_button.setEnabled(True)
        self.progress.setVisible(False)
        keys = set()
        log_entries = []
        errors = []
        duplicates = []
        items_by_source = {str(item.source): item for item in self.model.items}
        for result in results:
            if not isinstance(result, dict):
                continue
            source = result.get("source", "")
            item = items_by_source.get(source)
            if result.get("operation") == "error":
                errors.append(f"{Path(source).name} : {result.get('error', 'erreur inconnue')}")
                if item:
                    item.status = "Échec : " + result.get("error", "erreur inconnue")
                continue
            if result.get("operation") == "duplicate":
                duplicates.append(f"{Path(source).name} déjà présent : {result.get('duplicate_of', 'emplacement inconnu')}")
                keys.add(item.key if item else source)
                continue
            keys.add(item.key if item else source)
            log_entries.append(result)
            target = Path(result["target"])
            if target.exists() and item:
                self.search_index.upsert(target, item.classification, "classé", item.hierarchy_label)
            if result.get("operation") == "move":
                self.search_index.remove_missing()
        self.save_history(log_entries)
        self.model.remove_items(keys)
        summary = f"{len(log_entries)} fichier(s) classé(s) avec succès."
        if duplicates:
            summary += f" {len(duplicates)} doublon(s) exact(s) conservé(s) sans copie."
        if errors:
            summary += f" {len(errors)} échec(s) conservé(s) dans la file."
            QMessageBox.warning(self, "Classement partiellement terminé", summary + "\n\n" + "\n".join(errors[:8]))
        self.statusBar().showMessage(summary)
        self.update_badge()

    def save_history(self, entries):
        self.history_repository.append(entries)

    def undo_last(self):
        entries = self.history_repository.load()
        if not entries:
            QMessageBox.information(self, "Aucune opération", "Aucune opération récente n’est disponible pour être annulée.")
            return
        last = entries[-1]
        batch_id = last.get("batch_id")
        batch_size = sum(1 for entry in entries if batch_id and entry.get("batch_id") == batch_id) if batch_id else 1
        label = f"{batch_size} fichier(s) de la dernière session" if batch_size > 1 else f"« {Path(last.get('target', '')).name} »"
        if QMessageBox.question(self, "Annuler le classement", f"Annuler {label} ?\nLes fichiers modifiés depuis le classement seront conservés.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        undone, skipped = self.undo_service.undo_latest()
        self.search_index.remove_missing()
        message = f"{undone} opération(s) annulée(s)."
        if skipped:
            message += f" {len(skipped)} fichier(s) ignoré(s), car ils ont changé ou ne sont plus à la destination attendue."
            QMessageBox.warning(self, "Annulation partielle", message)
        self.statusBar().showMessage(message)

    def clear_queue(self):
        if not self.model.items:
            return
        if QMessageBox.question(self, "Vider la file", "Retirer toutes les propositions sans modifier les fichiers ?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            for item in self.model.items:
                self.search_index.delete_path(item.source)
            self.model.set_items([])
            self.statusBar().showMessage("File de classement vidée. Aucun fichier n’a été modifié.")
            self.update_badge()

    def open_duplicate_scan(self):
        paths = self.folder_paths()
        if not paths:
            return
        source, destination = paths
        dialog = DuplicateDialog([source, destination], self, self.duplicate_service, CONFIG_DIR / "quarantaine")
        dialog.exec()

    def open_history(self):
        dialog = HistoryDialog(self.history_repository, self)
        dialog.undo_requested.connect(self.undo_last)
        dialog.exec()

    def open_rules(self):
        dialog = RulesDialog(self.classifier, self)
        if dialog.exec() == QDialog.Accepted:
            self._save_config()
            self.statusBar().showMessage("Règles locales enregistrées. Les prochaines analyses en tiendront compte.")

    def on_worker_failed(self, message):
        self.scan_button.setEnabled(True)
        self.approve_button.setEnabled(True)
        self.progress.setVisible(False)
        QMessageBox.critical(self, "Opération interrompue", message)

    def closeEvent(self, event):
        if self.watch_button.text() == "Arrêter la surveillance":
            choice = QMessageBox.question(self, "Quitter MDJR classeur", "La surveillance va s’arrêter. Quitter quand même ?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if choice != QMessageBox.Yes:
                event.ignore()
                return
        self.watching = False
        self._stop_watch_observer()
        for worker in (self.scan_thread, self.apply_thread, self.search_worker):
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(1500)
        self._save_config()
        self.search_index.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    main()
