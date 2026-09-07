from __future__ import annotations

import json
import queue
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPalette

from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMainWindow, QMessageBox, QStackedWidget, QStatusBar,
    QTableView, QVBoxLayout, QWidget, QSystemTrayIcon,
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
from .application.agent import AgentLedger
from .application.learning import LearningMemory
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
from .presentation.pages import (
    Sidebar, DashboardPage, ImportPage, DocumentsPage, SearchPage, SettingsPage,
)

APP_NAME = "Classeur"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


CONFIG_DIR = Path.home() / ".mdjr_classeur"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "historique.json"
CACHE_FILE = CONFIG_DIR / "classifications.sqlite3"
SEARCH_INDEX_FILE = CONFIG_DIR / "search.sqlite3"
PREFERENCES_FILE = CONFIG_DIR / "preferences.json"


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

def build_stylesheet(theme: str, accent: QColor, background: str = "") -> str:
    if theme == "dark":
        window = "#0f1419"
        surface = "#1a2332"
        field = "#1e2d3d"
        text = "#e8f0f8"
        muted = "#7d95a8"
        border = "#2a3f52"
        sidebar_bg = "#0a0f14"
        sidebar_text = "#8ca3b8"
        sidebar_active_bg = accent.name()
        sidebar_active_text = "#ffffff"
        drop_bg = "#1a2332"
        drop_border = "#2a3f52"
        drop_hover = "#1e3a4f"
        badge_bg = accent.name()
    elif theme == "light":
        window = "#f5f7fa"
        surface = "#ffffff"
        field = "#ffffff"
        text = "#1a2b3c"
        muted = "#6b7f8e"
        border = "#dce3eb"
        sidebar_bg = "#1a2b3c"
        sidebar_text = "#94a7b8"
        sidebar_active_bg = accent.name()
        sidebar_active_text = "#ffffff"
        drop_bg = "#f0f4f8"
        drop_border = "#d0d8e0"
        drop_hover = "#e4ecf4"
        badge_bg = accent.name()
    else:
        window = "#f5f7fa"
        surface = "#ffffff"
        field = "#ffffff"
        text = "#1a2b3c"
        muted = "#6b7f8e"
        border = "#dce3eb"
        sidebar_bg = "#1a2b3c"
        sidebar_text = "#94a7b8"
        sidebar_active_bg = accent.name()
        sidebar_active_text = "#ffffff"
        drop_bg = "#f0f4f8"
        drop_border = "#d0d8e0"
        drop_hover = "#e4ecf4"
        badge_bg = accent.name()

    hover = accent.darker(115).name()
    image_rule = ""
    if background and Path(background).expanduser().is_file():
        image_rule = f'background-image: url("{Path(background).expanduser().as_posix()}"); background-position: center; background-repeat: no-repeat;'

    return f"""
        QMainWindow {{ background-color: {window}; }}

        /* Sidebar */
        QFrame#sidebar {{ background: {sidebar_bg}; border: none; }}
        QLabel#sidebarLogo {{ color: {sidebar_active_text}; font-size: 22px; font-weight: 800; padding: 8px 0; }}
        QLabel#sidebarVersion {{ color: {muted}; font-size: 11px; }}
        SidebarButton {{ background: transparent; color: {sidebar_text}; border: none; border-radius: 8px; padding: 8px 12px; text-align: left; font-size: 13px; font-weight: 600; }}
        SidebarButton:hover {{ background: rgba(255,255,255,0.06); color: {sidebar_active_text}; }}
        SidebarButton:checked {{ background: {sidebar_active_bg}; color: {sidebar_active_text}; }}

        /* General */
        QLabel {{ color: {text}; }}
        QLabel#pageTitle {{ font-size: 24px; font-weight: 800; color: {text}; }}
        QLabel#pageSubtitle {{ font-size: 13px; color: {muted}; margin-bottom: 4px; }}
        QLabel#sectionTitle {{ font-size: 15px; font-weight: 700; color: {text}; }}
        QLabel#sectionDesc {{ font-size: 13px; color: {muted}; }}

        /* Stat cards */
        QFrame#statCard {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
        QLabel#statValue {{ color: {text}; font-size: 26px; font-weight: 800; }}
        QLabel#statCaption {{ color: {muted}; font-size: 12px; }}

        /* Panels */
        QFrame#quickActions, QFrame#statusPanel, QFrame#foldersFrame, QFrame#settingsSection {{
            background: {surface}; border: 1px solid {border}; border-radius: 12px;
        }}

        /* Inputs */
        QLineEdit, QTextEdit, QComboBox, QSpinBox {{
            background: {field}; color: {text}; border: 1px solid {border}; border-radius: 8px; padding: 8px;
        }}
        QLineEdit#searchInput {{ font-size: 14px; padding: 10px 14px; }}

        /* Buttons */
        QPushButton {{
            background: {accent.name()}; color: white; border: none; border-radius: 8px;
            padding: 10px 18px; font-weight: 700; font-size: 13px;
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:disabled {{ background: {border}; color: {muted}; }}
        QPushButton#secondary {{ background: {surface}; color: {text}; border: 1px solid {border}; }}
        QPushButton#secondary:hover {{ background: {drop_hover}; }}
        QPushButton#danger {{ background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }}
        QPushButton#danger:hover {{ background: #fee2e2; }}

        /* Table */
        QTableView, QTableWidget {{
            background: {surface}; color: {text}; border: 1px solid {border}; border-radius: 10px;
            gridline-color: {border}; selection-background-color: {accent.name()}; selection-color: white;
        }}
        QHeaderView::section {{
            background: {surface}; color: {muted}; padding: 10px; border: none; font-weight: 700;
        }}

        /* Checkboxes */
        QCheckBox {{ color: {text}; padding: 4px; }}

        /* Progress */
        QProgressBar {{ border: none; background: {border}; border-radius: 5px; height: 8px; text-align: center; }}
        QProgressBar::chunk {{ background: {accent.name()}; border-radius: 5px; }}

        /* Drop zone */
        QFrame#dropZone {{
            background: {drop_bg}; border: 2px dashed {drop_border}; border-radius: 16px;
        }}
        QFrame#dropZone[hovering="true"] {{
            background: {drop_hover}; border-color: {accent.name()};
        }}
        QLabel#dropIcon {{ font-size: 48px; color: {muted}; }}
        QLabel#dropLabel {{ font-size: 15px; font-weight: 600; color: {text}; }}
        QLabel#dropSublabel {{ font-size: 12px; color: {muted}; }}

        /* Badges */
        QLabel#pendingBadge {{
            background: {badge_bg}; color: white; border-radius: 10px;
            padding: 4px 12px; font-size: 12px; font-weight: 700;
        }}
        QLabel#statusBadge {{ font-weight: 700; font-size: 14px; }}
        QLabel#activityLabel {{ color: {muted}; font-size: 13px; }}
        QLabel#searchSummary {{ color: {muted}; font-size: 13px; }}

        /* Scroll areas */
        QScrollArea {{ border: none; background: transparent; }}
    """


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.preferences = load_preferences(PREFERENCES_FILE)
        set_language(str(self.preferences.get("language", "fr")))
        self.setWindowTitle(APP_NAME + " — " + tr("votre assistant documentaire local"))
        self.setWindowIcon(QIcon(str(resource_path("assets/mdjr.svg"))))
        self.resize(1380, 860)

        self.classifier = LocalClassifier.from_json(CONFIG_DIR / "regles.json")
        self.cache = ClassificationCache(CACHE_FILE)
        self.search_index = SearchIndex(SEARCH_INDEX_FILE)
        self.classification_service = ClassificationService(self.classifier, self.cache)
        self.agent_ledger = AgentLedger(CONFIG_DIR / "agent.sqlite3")
        self.learning_memory = LearningMemory(CONFIG_DIR / "learning.sqlite3")
        self.scan_service = ScanService(
            self.classification_service,
            ledger=self.agent_ledger,
            learning=self.learning_memory,
        )
        self.history_repository = HistoryRepository(LOG_FILE)
        self.undo_service = UndoService(self.history_repository)
        self.file_operation_service = FileOperationService(self.search_index.find_duplicate)
        self.duplicate_service = DuplicateService()
        self.plan_edit_service = PlanEditService()
        self.search_worker = None
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

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar()
        self.sidebar.page_selected.connect(self._switch_page)
        root.addWidget(self.sidebar)

        # Pages
        self.stack = QStackedWidget()

        # Page 0: Dashboard
        self.dashboard_page = DashboardPage()
        self.dashboard_page.scan_requested.connect(self.scan_existing)
        self.dashboard_page.watch_requested.connect(self.toggle_watch)
        self.dashboard_page.search_requested.connect(lambda: self.sidebar.select_page(3))
        self.dashboard_page.duplicate_requested.connect(self.open_duplicate_scan)
        self.stack.addWidget(self.dashboard_page)

        # Page 1: Import
        self.import_page = ImportPage()
        self.import_page.scan_requested.connect(self.scan_existing)
        self.import_page.watch_toggled.connect(self.toggle_watch)
        self.import_page.drop_zone.files_dropped.connect(self._on_files_dropped)
        self.import_page.auto_checkbox.stateChanged.connect(self.set_auto_mode)
        self.stack.addWidget(self.import_page)

        # Page 2: Documents
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        for col, mode in enumerate([
            QHeaderView.ResizeToContents, QHeaderView.Stretch, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.Stretch, QHeaderView.ResizeToContents,
            QHeaderView.ResizeToContents, QHeaderView.Stretch, QHeaderView.ResizeToContents,
        ]):
            if col < self.model.columnCount():
                self.table.horizontalHeader().setSectionResizeMode(col, mode)
        self.documents_page = DocumentsPage(self.table)
        self.documents_page.approve_requested.connect(self.apply_selected)
        self.documents_page.clear_requested.connect(self.clear_queue)
        self.documents_page.undo_requested.connect(self.undo_last)
        self.documents_page.history_requested.connect(self.open_history)
        self.documents_page.hierarchy_requested.connect(self.open_hierarchy_preview)
        self.documents_page._approve_high_confidence_cb = self.apply_high_confidence
        self.table.selectionModel().selectionChanged.connect(self.show_explanation)
        self.stack.addWidget(self.documents_page)

        # Page 3: Search
        self.search_page = SearchPage(self.search_index)
        self.search_page.open_file_requested.connect(self._open_file)
        self.stack.addWidget(self.search_page)

        # Page 4: Settings
        self.settings_page = SettingsPage()
        self.settings_page.preferences_requested.connect(self.open_preferences)
        self.settings_page.rules_requested.connect(self.open_rules)
        self.stack.addWidget(self.settings_page)

        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(tr("Bienvenue dans Classeur. Choisissez un dossier source pour commencer."))
        self._update_all_stats()

    def _switch_page(self, index: int):
        self.stack.setCurrentIndex(index)
        if index == 3:
            self.refresh_search_index()
            self.search_page.refresh_results()

    def _open_file(self, path_str: str):
        path = Path(path_str)
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ------------------------------------------------------------------
    # Preferences
    # ------------------------------------------------------------------

    def apply_preferences(self):
        theme = str(self.preferences.get("theme", "system"))
        accent = QColor(str(self.preferences.get("accent", "#1c8c70")))
        if not accent.isValid():
            accent = QColor("#1c8c70")
        background = str(self.preferences.get("background", ""))

        app = QApplication.instance()
        if theme == "dark" and app:
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor("#0f1419"))
            palette.setColor(QPalette.Base, QColor("#1e2d3d"))
            palette.setColor(QPalette.Text, QColor("#e8f0f8"))
            palette.setColor(QPalette.Button, QColor("#1a2332"))
            palette.setColor(QPalette.ButtonText, QColor("#e8f0f8"))
            app.setPalette(palette)
        elif app:
            app.setPalette(app.style().standardPalette())

        self.setStyleSheet(build_stylesheet(theme, accent, background))

    def open_preferences(self):
        dialog = PreferencesDialog(self.preferences, self)
        if dialog.exec() != QDialog.Accepted:
            return
        old_language = str(self.preferences.get("language", "fr"))
        self.preferences = dialog.values()
        save_preferences(PREFERENCES_FILE, self.preferences)
        set_language(str(self.preferences.get("language", "fr")))
        self.apply_preferences()
        self.setWindowTitle(APP_NAME + " — " + tr("votre assistant documentaire local"))
        if old_language != str(self.preferences.get("language", "fr")):
            QMessageBox.information(self, tr("Préférences"), tr("Les changements de langue seront appliqués au prochain démarrage."))

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(str(resource_path("assets/mdjr.svg"))))
        self.tray.setToolTip(APP_NAME)
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        show_action = QAction(tr("Ouvrir Classeur"), self)
        show_action.triggered.connect(self.showNormal)
        menu.addAction(show_action)
        quit_action = QAction(tr("Quitter"), self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.show()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self):
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
            self.import_page.source_edit.setText(data.get("source", ""))
            self.import_page.destination_edit.setText(data.get("destination", ""))
        except (OSError, json.JSONDecodeError):
            pass

    def _save_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_text(CONFIG_FILE, json.dumps({
            "version": 3,
            "source": self.import_page.source_edit.text(),
            "destination": self.import_page.destination_edit.text(),
        }, ensure_ascii=False, indent=2))
        self.classifier.save_json(CONFIG_DIR / "regles.json")

    # ------------------------------------------------------------------
    # Folder helpers
    # ------------------------------------------------------------------

    def folder_paths(self) -> tuple[Path, Path] | None:
        source_text = self.import_page.source_edit.text().strip()
        destination_text = self.import_page.destination_edit.text().strip()
        if not source_text or not destination_text:
            QMessageBox.warning(self, tr("Dossiers requis"), tr("Choisissez un dossier source et un dossier de classement."))
            return None
        try:
            source, destination = resolve_folder_pair(Path(source_text), Path(destination_text))
        except FolderPairError as exc:
            QMessageBox.warning(self, tr("Configuration invalide"), str(exc))
            return None
        self._save_config()
        return source, destination

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def scan_existing(self):
        paths = self.folder_paths()
        if not paths or (self.scan_thread and self.scan_thread.isRunning()):
            return
        source, destination = paths
        self.import_page.scan_button.setEnabled(False)
        self.import_page.progress.setVisible(True)
        self.import_page.progress.setRange(0, 0)
        self.statusBar().showMessage(tr("Analyse du dossier en cours…"))
        self._scan_seen = 0
        self._scan_added = 0
        self.scan_thread = ScanWorker(source, destination, self.classifier, self.cache, self.scan_service)
        self.scan_thread.batch_ready.connect(self.on_scan_batch)
        self.scan_thread.completed.connect(self.on_scan_completed)
        self.scan_thread.failed.connect(self.on_worker_failed)
        self.scan_thread.start()

    def on_scan_batch(self, items):
        self._scan_seen += len(items)
        added = self.model.add_items(items)
        self._scan_added += added
        for item in items:
            self.search_index.upsert_plan_item(item, "en attente")
        self.known_keys.update(item.key for item in items)
        self.statusBar().showMessage(
            f"Analyse : {self._scan_seen} fichier(s), {self._scan_added} proposition(s)"
        )
        self._update_all_stats()
        if self.import_page.auto_checkbox.isChecked() and items:
            self.execute_items(items)

    def on_scan_completed(self, items, count):
        self.import_page.scan_button.setEnabled(True)
        self.import_page.progress.setVisible(False)
        msg = f"Analyse terminée : {count} fichier(s), {self._scan_added} proposition(s)"
        self.statusBar().showMessage(msg)
        self.dashboard_page.set_activity(msg)
        self._update_all_stats()
        if self._scan_added and self.tray.isVisible():
            self.tray.showMessage(APP_NAME, f"{self._scan_added} fichier(s) prêt(s) à être classé(s).", QSystemTrayIcon.Information, 5000)
        if self._scan_added:
            self.sidebar.select_page(2)

    # ------------------------------------------------------------------
    # File watching
    # ------------------------------------------------------------------

    def _start_watch_observer(self, source: Path):
        if Observer is None:
            self.statusBar().showMessage(tr("Surveillance légère active (polling)."))
            return
        try:
            self.watch_observer = Observer()
            self.watch_observer.schedule(WatchEventHandler(self.event_queue), str(source), recursive=True)
            self.watch_observer.start()
            self.statusBar().showMessage(tr("Surveillance événementielle active."))
        except OSError:
            self.watch_observer = None

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
        source = Path(self.import_page.source_edit.text().strip()).expanduser()
        destination = Path(self.import_page.destination_edit.text().strip()).expanduser()
        if not source.exists() or not destination:
            return
        fresh = []
        try:
            for path in self._event_candidates(source, destination):
                key = self.file_key(path)
                path_id = str(path.resolve())
                if key not in self.known_keys:
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
                self._update_all_stats()
                if self.import_page.auto_checkbox.isChecked():
                    self.execute_items(fresh)
                if self.tray.isVisible():
                    self.tray.showMessage(APP_NAME, f"{len(fresh)} nouveau(x) fichier(s).", QSystemTrayIcon.Information, 4500)
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
        if not self.watching:
            if not self.folder_paths():
                return
            if bool(self.preferences.get("confirm_actions", True)):
                permission = QMessageBox.question(
                    self, tr("Surveillance"),
                    tr("Classeur va analyser les fichiers présents puis surveiller les nouveaux.\nLes fichiers ambigus seront placés dans « À trier ».\nAutoriser ?"),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if permission != QMessageBox.Yes:
                    return
            self.import_page.auto_checkbox.setChecked(True)
            self.watching = True
            source = Path(self.import_page.source_edit.text().strip()).expanduser()
            self._start_watch_observer(source)
            self.import_page.watch_button.setText(tr("Arrêter la surveillance"))
            self.import_page.watch_button.setObjectName("danger")
            self.import_page.watch_button.style().unpolish(self.import_page.watch_button)
            self.import_page.watch_button.style().polish(self.import_page.watch_button)
            self.dashboard_page.set_watch_active(True)
            self.scan_existing()
        else:
            self.watching = False
            self._stop_watch_observer()
            self.event_queue = queue.Queue()
            self.pending_signatures.clear()
            self.import_page.watch_button.setText(tr("Démarrer la surveillance"))
            self.import_page.watch_button.setObjectName("")
            self.import_page.watch_button.style().unpolish(self.import_page.watch_button)
            self.import_page.watch_button.style().polish(self.import_page.watch_button)
            self.dashboard_page.set_watch_active(False)
            self.statusBar().showMessage(tr("Surveillance arrêtée."))

    # ------------------------------------------------------------------
    # Drag & drop import
    # ------------------------------------------------------------------

    def _on_files_dropped(self, paths: list[Path]):
        source_text = self.import_page.source_edit.text().strip()
        if not source_text:
            first = paths[0]
            source = first if first.is_dir() else first.parent
            self.import_page.source_edit.setText(str(source))
            if not self.import_page.destination_edit.text():
                self.import_page.destination_edit.setText(str(source.parent / "MDJR_Classement"))
            self._save_config()
        self.scan_existing()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _search_roots(self) -> list[Path]:
        roots: list[Path] = []
        for value in (self.import_page.source_edit.text().strip(), self.import_page.destination_edit.text().strip()):
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
        self.search_page.refresh_results()
        self.statusBar().showMessage(f"Index actualisé : {count} élément(s).")

    def on_search_index_failed(self, message: str):
        self.statusBar().showMessage(f"Index partiel : {message}")

    # ------------------------------------------------------------------
    # Documents view
    # ------------------------------------------------------------------

    def show_explanation(self, selected, deselected):
        rows = selected.indexes()
        if not rows:
            self.documents_page.show_item_detail(None)
            return
        item = self.model.items[rows[0].row()]
        self.documents_page.show_item_detail(item)

    def open_hierarchy_preview(self):
        if not self.model.items:
            QMessageBox.information(self, tr("Arborescence vide"), tr("Analysez d'abord les fichiers."))
            return
        HierarchyDialog(self.model.items, self).exec()

    # ------------------------------------------------------------------
    # Apply / classify
    # ------------------------------------------------------------------

    def set_auto_mode(self, state):
        self.auto_mode = state == Qt.Checked

    def apply_selected(self):
        items = self.model.selected_items()
        if not items:
            QMessageBox.information(self, tr("Aucun élément"), tr("Sélectionnez au moins un fichier."))
            return
        low = sum(item.confidence < 50 for item in items)
        message = f"Classeur va organiser {len(items)} fichier(s)."
        if low:
            message += f"\n\n{low} proposition(s) ont une confiance faible."
        if bool(self.preferences.get("confirm_actions", True)):
            if QMessageBox.question(self, tr("Classer"), message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        self.execute_items(items)

    def apply_high_confidence(self):
        items = [item for item in self.model.items if item.confidence >= 80]
        if not items:
            QMessageBox.information(self, tr("Aucun élément"), tr("Aucun fichier avec une confiance ≥80 %."))
            return
        message = f"Classer automatiquement {len(items)} fichier(s) avec confiance ≥80 % ?"
        if QMessageBox.question(self, tr("Classement automatique"), message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.execute_items(items)

    def execute_items(self, items):
        if self.apply_thread and self.apply_thread.isRunning():
            return
        mode = self.import_page.mode_combo.currentData() or "copy"
        for item in items:
            if item.human_corrected_fields:
                self.learning_memory.record(
                    path=item.source, fingerprint=item.sha256,
                    text_signature=item.normalized_text_sha256,
                    subject=item.classification.subject,
                    category=item.classification.category,
                    hierarchy=item.hierarchy_label,
                    suggested_name=item.suggested_name,
                    context=item.classification.extracted_preview,
                )
        self.documents_page.approve_btn.setEnabled(False)
        self.import_page.progress.setVisible(True)
        self.import_page.progress.setRange(0, 100)
        self.import_page.progress.setValue(0)
        self.apply_thread = ApplyWorker(items, mode, self.file_operation_service)
        self.apply_thread.progress.connect(lambda value, name: (
            self.import_page.progress.setValue(value),
            self.statusBar().showMessage(f"Classement : {name}"),
        ))
        self.apply_thread.completed.connect(self.on_apply_completed)
        self.apply_thread.failed.connect(self.on_worker_failed)
        self.apply_thread.start()

    def on_apply_completed(self, results):
        self.documents_page.approve_btn.setEnabled(True)
        self.import_page.progress.setVisible(False)
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
                errors.append(f"{Path(source).name} : {result.get('error', '?')}")
                if item:
                    item.status = "Échec : " + result.get("error", "?")
                continue
            if result.get("operation") == "duplicate":
                duplicates.append(f"{Path(source).name} doublon")
                keys.add(item.key if item else source)
                continue
            keys.add(item.key if item else source)
            log_entries.append(result)
            target = Path(result["target"])
            if target.exists() and item:
                self.search_index.upsert(target, item.classification, "classé", item.hierarchy_label)
            if result.get("operation") == "move":
                self.search_index.remove_missing()
        self.history_repository.append(log_entries)
        self.model.remove_items(keys)
        summary = f"{len(log_entries)} fichier(s) classé(s)."
        if duplicates:
            summary += f" {len(duplicates)} doublon(s)."
        if errors:
            summary += f" {len(errors)} échec(s)."
            QMessageBox.warning(self, tr("Classement partiel"), summary + "\n\n" + "\n".join(errors[:8]))
        self.statusBar().showMessage(summary)
        self.dashboard_page.set_activity(summary)
        self._update_all_stats()

    # ------------------------------------------------------------------
    # Undo / History
    # ------------------------------------------------------------------

    def undo_last(self):
        entries = self.history_repository.load()
        if not entries:
            QMessageBox.information(self, tr("Aucune opération"), tr("Rien à annuler."))
            return
        last = entries[-1]
        batch_id = last.get("batch_id")
        batch_size = sum(1 for e in entries if batch_id and e.get("batch_id") == batch_id) if batch_id else 1
        label = f"{batch_size} fichier(s)" if batch_size > 1 else f"« {Path(last.get('target', '')).name} »"
        if QMessageBox.question(self, tr("Annuler"), f"Annuler {label} ?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        undone, skipped = self.undo_service.undo_latest()
        self.search_index.remove_missing()
        msg = f"{undone} opération(s) annulée(s)."
        if skipped:
            msg += f" {len(skipped)} ignorée(s)."
        self.statusBar().showMessage(msg)

    def clear_queue(self):
        if not self.model.items:
            return
        if QMessageBox.question(self, tr("Vider"), tr("Retirer toutes les propositions ?"), QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            for item in self.model.items:
                self.search_index.delete_path(item.source)
            self.model.set_items([])
            self.statusBar().showMessage(tr("File vidée."))
            self._update_all_stats()

    # ------------------------------------------------------------------
    # Duplicates
    # ------------------------------------------------------------------

    def open_duplicate_scan(self):
        paths = self.folder_paths()
        if not paths:
            return
        source, destination = paths
        DuplicateDialog([source, destination], self, self.duplicate_service, CONFIG_DIR / "quarantaine").exec()

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def open_history(self):
        dialog = HistoryDialog(self.history_repository, self)
        dialog.undo_requested.connect(self.undo_last)
        dialog.exec()

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def open_rules(self):
        dialog = RulesDialog(self.classifier, self)
        if dialog.exec() == QDialog.Accepted:
            self._save_config()
            self.statusBar().showMessage(tr("Règles enregistrées."))

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def _update_all_stats(self):
        items = self.model.items
        pending = len(items)
        avg_conf = round(sum(i.confidence for i in items) / len(items)) if items else 0
        indexed = self.search_index.connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        self.dashboard_page.update_stats(pending, indexed, avg_conf, 0)
        self.documents_page.set_pending_count(pending)

    # ------------------------------------------------------------------
    # Error handler
    # ------------------------------------------------------------------

    def on_worker_failed(self, message):
        self.import_page.scan_button.setEnabled(True)
        self.documents_page.approve_btn.setEnabled(True)
        self.import_page.progress.setVisible(False)
        QMessageBox.critical(self, tr("Erreur"), message)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        if self.watching:
            if QMessageBox.question(self, tr("Quitter"), tr("La surveillance va s'arrêter. Quitter ?"), QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
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
        self.agent_ledger.close()
        self.learning_memory.close()
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
