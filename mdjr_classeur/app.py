from __future__ import annotations

import json
import queue
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPixmap
try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # Le profil minimal reste fonctionnel sans watchdog.
    FileSystemEventHandler = object
    Observer = None

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QSplitter,
    QStatusBar, QTableView, QTextEdit, QToolBar, QVBoxLayout, QWidget, QDialog,
    QDialogButtonBox, QFormLayout, QSpinBox, QSystemTrayIcon, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem,
)

from .cache import ClassificationCache
from .classifier import LocalClassifier, Classification, clean_filename, fold
from .dedupe import DuplicateReport, delete_duplicates, format_bytes, quarantine_duplicates, scan_duplicates
from .search_index import SearchIndex, SearchRecord

APP_NAME = "MDJR classeur"


def semantic_tokens(value: str) -> set[str]:
    normalized = fold(value)
    aliases = {
        "mathematiques": ["mathematiques", "mathematique", "maths", "math"],
        "informatique": ["informatique", "info"],
        "td": ["travaux diriges", "travaux dirige", "td"],
        "tp": ["travaux pratiques", "travaux pratique", "tp"],
        "examen": ["examens", "examen", "exam", "partiel"],
        "administratif": ["administratif", "administrative", "administration"],
    }
    for canonical, variants in aliases.items():
        for variant in sorted(variants, key=len, reverse=True):
            normalized = re.sub(rf"(?<!\w){re.escape(variant)}(?!\w)", canonical, normalized)
    return set(normalized.split())


def reuse_existing_folder(parent: Path, desired: str) -> tuple[Path, str]:
    """Réutilise un dossier existant si son nom normalisé correspond de façon sûre."""
    desired_clean = clean_filename(desired, "Autre")
    if not parent.exists():
        return parent / desired_clean, "nouveau dossier prévu"
    desired_tokens = semantic_tokens(desired_clean)
    best: tuple[Path, float] | None = None
    try:
        children = [child for child in parent.iterdir() if child.is_dir() and not child.is_symlink()]
    except OSError:
        children = []
    for child in children:
        child_tokens = semantic_tokens(child.name)
        if not child_tokens or not desired_tokens:
            continue
        if child_tokens == desired_tokens:
            return child, "dossier existant réutilisé"
        overlap = len(desired_tokens & child_tokens) / max(len(desired_tokens), len(child_tokens))
        if overlap >= 0.8 and (best is None or overlap > best[1]):
            best = (child, overlap)
    if best:
        return best[0], "dossier existant rapproché"
    return parent / desired_clean, "nouveau dossier prévu"


def build_destination(root: Path, classification: Classification, source_suffix: str, source_stem: str) -> tuple[Path, Path, str]:
    """Construit une destination adaptative et réutilise les dossiers existants à chaque niveau."""
    if classification.hierarchy:
        requested_levels = list(classification.hierarchy)
    else:
        requested_levels = [classification.subject or "À trier", classification.category or "Autre"]
    levels: list[str] = []
    for level in requested_levels:
        cleaned = clean_filename(level, "Autre")
        if cleaned not in levels and cleaned not in {"À trier", "Autre"}:
            levels.append(cleaned)
    if not levels:
        levels = ["À trier", "Autre"]
    levels = levels[:5]
    current = root
    reasons: list[str] = []
    for level in levels:
        current, reason = reuse_existing_folder(current, level)
        reasons.append(f"{level} : {reason}")
    title = clean_filename(classification.title or source_stem, "Document")
    filename = title
    return current, (current / filename).with_suffix(source_suffix.lower()), "; ".join(reasons)


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relative


CONFIG_DIR = Path.home() / ".mdjr_classeur"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "historique.json"
CACHE_FILE = CONFIG_DIR / "classifications.sqlite3"
SEARCH_INDEX_FILE = CONFIG_DIR / "search.sqlite3"


def classify_cached(classifier: LocalClassifier, cache: ClassificationCache, path: Path) -> Classification:
    cached = cache.get(path, classifier.rules_version)
    if cached is not None:
        return cached
    classification = classifier.classify(path)
    cache.put(path, classifier.rules_version, classification)
    return classification


@dataclass
class PlanItem:
    source: Path
    classification: Classification
    destination_dir: Path
    destination_file: Path
    status: str = "En attente"
    existing: bool = False
    destination_root: Path | None = None
    destination_reason: str = ""

    @property
    def confidence(self) -> int:
        return self.classification.confidence

    @property
    def key(self) -> str:
        try:
            stat = self.source.stat()
            return f"{self.source.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"
        except OSError:
            return str(self.source.resolve())

    @property
    def hierarchy_label(self) -> str:
        if self.destination_root:
            try:
                relative = self.destination_dir.relative_to(self.destination_root)
                return " / ".join(relative.parts)
            except ValueError:
                pass
        return " / ".join(self.classification.hierarchy or (self.classification.subject, self.classification.category))


class WatchEventHandler(FileSystemEventHandler):
    def __init__(self, event_queue):
        super().__init__()
        self.event_queue = event_queue

    def _enqueue(self, path):
        if path:
            self.event_queue.put(Path(path))

    def on_created(self, event):
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._enqueue(event.dest_path)


class ScanWorker(QThread):
    completed = Signal(object, int)
    failed = Signal(str)

    def __init__(self, source_dir: Path, destination_dir: Path, classifier: LocalClassifier, cache: ClassificationCache):
        super().__init__()
        self.source_dir = source_dir
        self.destination_dir = destination_dir
        self.classifier = classifier
        self.cache = cache

    def run(self):
        try:
            items = []
            if not self.source_dir.exists():
                raise FileNotFoundError("Le dossier surveillé n’existe pas.")
            for path in sorted(self.source_dir.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                try:
                    path.relative_to(self.destination_dir)
                    continue
                except ValueError:
                    pass
                classification = classify_cached(self.classifier, self.cache, path)
                destination_dir, destination_file, reason = build_destination(self.destination_dir, classification, path.suffix, path.stem)
                items.append(PlanItem(path, classification, destination_dir, destination_file, existing=True, destination_root=self.destination_dir, destination_reason=reason))
            self.completed.emit(items, len(items))
        except Exception as exc:
            self.failed.emit(str(exc))


class ApplyWorker(QThread):
    completed = Signal(object)
    progress = Signal(int, str)
    failed = Signal(str)

    def __init__(self, items: list[PlanItem], mode: str):
        super().__init__()
        self.items = items
        self.mode = mode

    @staticmethod
    def unique_target(target: Path) -> Path:
        if not target.exists():
            return target
        for index in range(1, 10000):
            candidate = target.with_name(f"{target.stem} ({index}){target.suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError("Impossible de trouver un nom libre pour ce fichier.")

    def run(self):
        results = []
        try:
            total = max(1, len(self.items))
            for index, item in enumerate(self.items, start=1):
                if not item.source.exists():
                    item.status = "Source introuvable"
                    results.append(item)
                    continue
                item.destination_dir.mkdir(parents=True, exist_ok=True)
                target = self.unique_target(item.destination_file)
                if self.mode == "Déplacer l’original":
                    shutil.move(str(item.source), str(target))
                    operation = "move"
                else:
                    shutil.copy2(str(item.source), str(target))
                    operation = "copy"
                item.destination_file = target
                item.status = "Classé"
                results.append({"source": str(item.source), "target": str(target), "operation": operation, "timestamp": time.time()})
                self.progress.emit(int(index * 100 / total), item.source.name)
            self.completed.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class SearchIndexWorker(QThread):
    completed = Signal(int)
    failed = Signal(str)

    def __init__(self, roots: list[Path], index: SearchIndex, classifier: LocalClassifier, cache: ClassificationCache, pending_items=None):
        super().__init__()
        self.roots = roots
        self.index = index
        self.classifier = classifier
        self.cache = cache
        self.pending_items = pending_items or []

    def run(self):
        worker_index = SearchIndex(self.index.database_path)
        try:
            indexed = 0
            seen: set[str] = set()
            for root in self.roots:
                if not root.exists() or not root.is_dir():
                    continue
                for path in root.rglob("*"):
                    if not path.is_file() or path.is_symlink():
                        continue
                    resolved = str(path.resolve())
                    seen.add(resolved)
                    if not worker_index.needs_update(path, "classé"):
                        continue
                    classification = classify_cached(self.classifier, self.cache, path)
                    worker_index.upsert(path, classification, "classé", " / ".join(classification.hierarchy))
                    indexed += 1
            for item in self.pending_items:
                worker_index.upsert_plan_item(item, "en attente")
                seen.add(str(item.source.resolve()))
                indexed += 1
            worker_index.remove_missing()
            self.completed.emit(indexed)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            worker_index.close()


class DuplicateWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, roots: list[Path]):
        super().__init__()
        self.roots = roots

    def run(self):
        try:
            self.completed.emit(scan_duplicates(self.roots))
        except Exception as exc:
            self.failed.emit(str(exc))


class DuplicateDialog(QDialog):
    def __init__(self, roots: list[Path], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Analyse intelligente des doublons - MDJR classeur")
        self.resize(980, 620)
        self.roots = roots
        self.report: DuplicateReport | None = None
        self.worker: DuplicateWorker | None = None
        layout = QVBoxLayout(self)
        intro = QLabel("MDJR compare le contenu réel des fichiers et la structure complète des dossiers. Rien n’est supprimé automatiquement.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.summary = QLabel("Prêt à analyser les emplacements sélectionnés.")
        self.summary.setStyleSheet("font-size: 15px; font-weight: 700; color: #17324d;")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Type", "Éléments identiques", "Espace récupérable", "Emplacements"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.scan_button = QPushButton("Relancer l’analyse")
        self.scan_button.setObjectName("secondary")
        self.scan_button.clicked.connect(self.scan)
        buttons.addWidget(self.scan_button)
        self.quarantine_button = QPushButton("Mettre les copies en quarantaine")
        self.quarantine_button.setObjectName("danger")
        self.quarantine_button.setEnabled(False)
        self.quarantine_button.clicked.connect(self.quarantine)
        buttons.addWidget(self.quarantine_button)
        self.delete_button = QPushButton("Supprimer définitivement")
        self.delete_button.setObjectName("danger")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_permanently)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        close_button = QPushButton("Fermer")
        close_button.setObjectName("secondary")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.scan()

    def scan(self):
        if self.worker and self.worker.isRunning():
            return
        self.scan_button.setEnabled(False)
        self.quarantine_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.summary.setText("Analyse en cours : empreintes des fichiers et structures de dossiers…")
        self.table.setRowCount(0)
        self.worker = DuplicateWorker(self.roots)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_completed(self, report: DuplicateReport):
        self.report = report
        self.scan_button.setEnabled(True)
        duplicate_files = report.total_file_duplicates
        duplicate_folders = report.total_folder_duplicates
        self.summary.setText(
            f"{report.scanned_files} fichier(s) et {report.scanned_folders} dossier(s) analysés - "
            f"{duplicate_files} doublon(s) de fichier, {duplicate_folders} dossier(s) équivalent(s), "
            f"{format_bytes(report.recoverable_bytes)} potentiellement récupérables."
        )
        rows = []
        for group in report.file_groups:
            rows.append(("Fichiers identiques", group.duplicate_count, format_bytes(group.recoverable_bytes), "\n".join(str(path) for path in group.files)))
        for group in report.folder_groups:
            rows.append(("Dossiers équivalents", group.duplicate_count, format_bytes(group.total_size * group.duplicate_count), "\n".join(str(path) for path in group.folders)))
        self.table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.quarantine_button.setEnabled(bool(rows))
        self.delete_button.setEnabled(bool(rows))

    def on_failed(self, message: str):
        self.scan_button.setEnabled(True)
        self.summary.setText("L’analyse n’a pas pu être terminée.")
        QMessageBox.critical(self, "Analyse impossible", message)

    def quarantine(self):
        if not self.report or not (self.report.file_groups or self.report.folder_groups):
            return
        answer = QMessageBox.question(
            self,
            "Confirmer la quarantaine",
            "MDJR va conserver une copie de référence pour chaque groupe et déplacer les copies excédentaires vers une quarantaine locale.\n\nAucune suppression définitive ne sera effectuée. Continuer ?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        moved = quarantine_duplicates(self.report, CONFIG_DIR / "quarantaine")
        self.summary.setText(f"{len(moved)} élément(s) déplacé(s) vers la quarantaine locale.")
        self.quarantine_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        QMessageBox.information(self, "Quarantaine terminée", "Les copies ont été déplacées vers .mdjr_classeur/quarantaine. Tu peux les restaurer manuellement si nécessaire.")
        self.scan()

    def delete_permanently(self):
        if not self.report or not (self.report.file_groups or self.report.folder_groups):
            return
        answer = QMessageBox.warning(
            self,
            "Suppression définitive",
            "Cette action supprimera définitivement les copies excédentaires et les dossiers équivalents retenus. Elle ne passe pas par la corbeille et ne peut pas être annulée par MDJR.\n\nEs-tu absolument certain de vouloir continuer ?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        removed = delete_duplicates(self.report)
        self.summary.setText(f"{removed} élément(s) supprimé(s) définitivement.")
        self.delete_button.setEnabled(False)
        self.quarantine_button.setEnabled(False)
        QMessageBox.information(self, "Suppression terminée", f"{removed} élément(s) ont été supprimés définitivement.")
        self.scan()


class SearchDialog(QDialog):
    def __init__(self, index: SearchIndex, parent=None):
        super().__init__(parent)
        self.index = index
        self.records: list[SearchRecord] = []
        self.setWindowTitle("Recherche rapide - MDJR classeur")
        self.resize(1050, 650)
        layout = QVBoxLayout(self)
        heading = QLabel("Recherche documentaire locale")
        heading.setStyleSheet("font-size: 22px; font-weight: 800; color: #17324d;")
        layout.addWidget(heading)
        intro = QLabel("Recherche dans les noms, matières, natures, chemins, titres et extraits de contenu. Aucun document ne quitte ton ordinateur.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        controls = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Ex. intégrales, attestation, projet web, semestre 2…")
        self.query_edit.setClearButtonEnabled(True)
        self.query_edit.textChanged.connect(self.refresh_results)
        controls.addWidget(self.query_edit, 1)
        self.status_combo = QComboBox()
        self.status_combo.addItems(["Tous", "classé", "en attente"])
        self.status_combo.currentTextChanged.connect(self.refresh_results)
        controls.addWidget(QLabel("Statut :"))
        controls.addWidget(self.status_combo)
        refresh = QPushButton("Actualiser")
        refresh.setObjectName("secondary")
        refresh.clicked.connect(self.refresh_results)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.summary = QLabel("Saisis un mot-clé pour commencer.")
        self.summary.setStyleSheet("font-weight: 700; color: #47627a;")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Fichier", "Matière", "Nature", "Arborescence", "Statut", "Emplacement"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self.open_selected())
        layout.addWidget(self.table, 1)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(120)
        self.preview.setPlaceholderText("Sélectionne un résultat pour afficher son titre et son extrait.")
        self.table.itemSelectionChanged.connect(self.show_preview)
        layout.addWidget(self.preview)
        buttons = QHBoxLayout()
        open_button = QPushButton("Ouvrir le fichier")
        open_button.clicked.connect(self.open_selected)
        buttons.addWidget(open_button)
        folder_button = QPushButton("Afficher le dossier")
        folder_button.setObjectName("secondary")
        folder_button.clicked.connect(self.open_folder)
        buttons.addWidget(folder_button)
        buttons.addStretch()
        close_button = QPushButton("Fermer")
        close_button.setObjectName("secondary")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def refresh_results(self):
        try:
            self.records = self.index.search(self.query_edit.text(), self.status_combo.currentText())
        except Exception as exc:
            self.records = []
            self.summary.setText(f"Recherche temporairement indisponible : {exc}")
            return
        self.table.setRowCount(len(self.records))
        for row, record in enumerate(self.records):
            values = [record.name, record.subject, record.category, record.hierarchy, record.status, record.path]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        query = self.query_edit.text().strip()
        label = f" pour « {query} »" if query else " dans l’index local"
        self.summary.setText(f"{len(self.records)} résultat(s){label}.")
        if self.records:
            self.table.selectRow(0)
        else:
            self.preview.clear()

    def _selected_record(self) -> SearchRecord | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        return self.records[row] if 0 <= row < len(self.records) else None

    def show_preview(self):
        record = self._selected_record()
        if not record:
            return
        self.preview.setPlainText(f"Titre : {record.title or record.name}\n\nArborescence : {record.hierarchy or 'non déterminée'}\n\nExtrait :\n{record.preview or 'Aucun extrait textuel disponible.'}\n\nChemin : {record.path}")

    def open_selected(self):
        record = self._selected_record()
        if record:
            QDesktopServices.openUrl(QUrl.fromLocalFile(record.path))

    def open_folder(self):
        record = self._selected_record()
        if record:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(record.path).parent)))


class PlanModel(QAbstractTableModel):
    headers = ["Fichier", "Matière", "Nature", "Arborescence", "Confiance", "Destination", "État"]

    def __init__(self):
        super().__init__()
        self.items: list[PlanItem] = []
        self.checked: set[str] = set()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 7

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        review = "À vérifier" if item.classification.needs_review else "Proposition fiable"
        values = [item.source.name, item.classification.subject, item.classification.category, item.hierarchy_label, f"{item.confidence} % - {review}", str(item.destination_file), item.status]
        if role in (Qt.DisplayRole, Qt.EditRole):
            return values[index.column()]
        if role == Qt.CheckStateRole and index.column() == 0:
            return Qt.Checked if item.key in self.checked else Qt.Unchecked
        if role == Qt.ForegroundRole and index.column() == 4:
            return QColor("#159570" if item.confidence >= 75 else "#cc8a20" if item.confidence >= 45 else "#d9534f")
        if role == Qt.ToolTipRole:
            return item.classification.reason
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        item = self.items[index.row()]
        if index.column() == 0 and role == Qt.CheckStateRole:
            if value == Qt.Checked:
                self.checked.add(item.key)
            else:
                self.checked.discard(item.key)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        if role == Qt.EditRole and index.column() in (1, 2):
            text = str(value).strip() or (item.classification.subject if index.column() == 1 else item.classification.category)
            if index.column() == 1:
                item.classification.subject = text
            else:
                item.classification.category = text
            item.classification.hierarchy = tuple(part for part in (item.classification.year, item.classification.domain, item.classification.subject, item.classification.topic, item.classification.category) if part and part not in {"À trier", "Autre"})
            self.rebuild_destination(item)
            self.dataChanged.emit(index, self.index(index.row(), 6), [Qt.DisplayRole, Qt.EditRole])
            return True
        return False

    def flags(self, index):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemIsUserCheckable
        if index.column() in (1, 2):
            flags |= Qt.ItemIsEditable
        return flags

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None

    def rebuild_destination(self, item: PlanItem):
        root = item.destination_root or item.destination_dir.parents[1]
        item.destination_dir, item.destination_file, item.destination_reason = build_destination(root, item.classification, item.source.suffix, item.source.stem)

    def set_items(self, items: list[PlanItem]):
        self.beginResetModel()
        self.items = items
        self.checked = {item.key for item in items}
        self.endResetModel()

    def selected_items(self) -> list[PlanItem]:
        return [item for item in self.items if item.key in self.checked]

    def add_items(self, items: list[PlanItem]):
        existing_keys = {item.key for item in self.items}
        fresh = [item for item in items if item.key not in existing_keys]
        if not fresh:
            return 0
        start = len(self.items)
        self.beginInsertRows(QModelIndex(), start, start + len(fresh) - 1)
        self.items.extend(fresh)
        self.checked.update(item.key for item in fresh)
        self.endInsertRows()
        return len(fresh)

    def remove_items(self, keys: set[str]):
        self.beginResetModel()
        self.items = [item for item in self.items if item.key not in keys]
        self.checked -= keys
        self.endResetModel()


class RulesDialog(QDialog):
    def __init__(self, classifier: LocalClassifier, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Règles intelligentes - MDJR classeur")
        self.resize(720, 520)
        self.classifier = classifier
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Modifie les mots-clés séparés par des virgules. Les changements restent locaux."))
        self.subjects = QTextEdit()
        self.categories = QTextEdit()
        self.domains = QTextEdit()
        self.topics = QTextEdit()
        self.subjects.setPlainText("\n".join(f"{name}: {', '.join(words)}" for name, words in classifier.subjects.items()))
        self.categories.setPlainText("\n".join(f"{name}: {', '.join(words)}" for name, words in classifier.categories.items()))
        self.domains.setPlainText("\n".join(f"{name}: {', '.join(words)}" for name, words in classifier.domains.items()))
        self.topics.setPlainText("\n".join(f"{name}: {', '.join(words)}" for name, words in classifier.topics.items()))
        form = QFormLayout()
        form.addRow("Matières", self.subjects)
        form.addRow("Natures", self.categories)
        form.addRow("Domaines", self.domains)
        form.addRow("Thèmes", self.topics)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        def parse(text: str):
            result = {}
            for line in text.splitlines():
                if ":" in line:
                    name, words = line.split(":", 1)
                    result[name.strip()] = [word.strip() for word in words.split(",") if word.strip()]
            return result
        subjects = parse(self.subjects.toPlainText())
        categories = parse(self.categories.toPlainText())
        domains = parse(self.domains.toPlainText())
        topics = parse(self.topics.toPlainText())
        if subjects:
            self.classifier.subjects = subjects
        if categories:
            self.classifier.categories = categories
        if domains:
            self.classifier.domains = domains
        if topics:
            self.classifier.topics = topics
        super().accept()


class HierarchyDialog(QDialog):
    def __init__(self, items: list[PlanItem], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aperçu de l’arborescence - MDJR classeur")
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        intro = QLabel("Voici l’organisation proposée avant classement. Les dossiers existants sont réutilisés lorsque leur nom est compatible.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Organisation proposée", "Fichiers"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 650)
        roots: dict[tuple[str, ...], QTreeWidgetItem] = {}
        counts: dict[tuple[str, ...], int] = {}
        for item in items:
            parts = tuple(part for part in item.hierarchy_label.split(" / ") if part) or ("À trier", "Autre")
            parent = None
            prefix: list[str] = []
            for part in parts:
                prefix.append(part)
                key = tuple(prefix)
                node = roots.get(key)
                if node is None:
                    node = QTreeWidgetItem([part, ""])
                    if parent is None:
                        self.tree.addTopLevelItem(node)
                    else:
                        parent.addChild(node)
                    roots[key] = node
                parent = node
            counts[parts] = counts.get(parts, 0) + 1
            if parent is not None:
                parent.setText(1, str(counts[parts]))
        self.tree.expandToDepth(2)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MDJR classeur - votre assistant documentaire local")
        self.setWindowIcon(QIcon(str(resource_path("assets/mdjr.svg"))))
        self.resize(1320, 820)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.classifier = LocalClassifier.from_json(CONFIG_DIR / "regles.json")
        self.cache = ClassificationCache(CACHE_FILE)
        self.search_index = SearchIndex(SEARCH_INDEX_FILE)
        self.search_worker = None
        self.search_dialog = None
        self.model = PlanModel()
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
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(16)

        hero = QFrame(objectName="hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(26, 22, 26, 22)
        title_box = QVBoxLayout()
        title = QLabel("MDJR classeur", objectName="title")
        subtitle = QLabel("Le classeur intelligent qui comprend vos documents - en local, avec contrôle total.", objectName="subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hero_layout.addLayout(title_box)
        hero_layout.addStretch()
        self.status_badge = QLabel("●  Surveillance inactive")
        self.status_badge.setStyleSheet("color: #ffcf66; font-weight: 700; font-size: 14px;")
        hero_layout.addWidget(self.status_badge, alignment=Qt.AlignVCenter)
        root.addWidget(hero)

        paths = QFrame()
        paths_layout = QVBoxLayout(paths)
        paths_layout.setContentsMargins(0, 0, 0, 0)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Dossier à surveiller"))
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Choisis le dossier où arrivent les fichiers…")
        source_row.addWidget(self.source_edit, 1)
        source_button = QPushButton("Parcourir")
        source_button.setObjectName("secondary")
        source_button.clicked.connect(self.choose_source)
        source_row.addWidget(source_button)
        paths_layout.addLayout(source_row)
        destination_row = QHBoxLayout()
        destination_row.addWidget(QLabel("Dossier de classement"))
        self.destination_edit = QLineEdit()
        self.destination_edit.setPlaceholderText("Choisis le dossier qui contiendra l’organisation finale…")
        destination_row.addWidget(self.destination_edit, 1)
        destination_button = QPushButton("Parcourir")
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
        self.pending_stat = stat_card("fichiers en attente")
        self.reuse_stat = stat_card("destinations réutilisées")
        self.confidence_stat = stat_card("confiance moyenne")
        root.addLayout(stats_row)

        actions = QHBoxLayout()
        self.scan_button = QPushButton("Analyser les fichiers existants")
        self.scan_button.clicked.connect(self.scan_existing)
        actions.addWidget(self.scan_button)
        self.watch_button = QPushButton("Démarrer la surveillance")
        self.watch_button.clicked.connect(self.toggle_watch)
        actions.addWidget(self.watch_button)
        self.approve_button = QPushButton("Classer les éléments sélectionnés")
        self.approve_button.clicked.connect(self.apply_selected)
        actions.addWidget(self.approve_button)
        self.clear_button = QPushButton("Vider la file")
        self.clear_button.setObjectName("danger")
        self.clear_button.clicked.connect(self.clear_queue)
        actions.addWidget(self.clear_button)
        self.undo_button = QPushButton("Annuler la dernière opération")
        self.undo_button.setObjectName("secondary")
        self.undo_button.clicked.connect(self.undo_last)
        actions.addWidget(self.undo_button)
        self.duplicate_button = QPushButton("Scanner les doublons")
        self.duplicate_button.setObjectName("secondary")
        self.duplicate_button.clicked.connect(self.open_duplicate_scan)
        actions.addWidget(self.duplicate_button)
        self.hierarchy_button = QPushButton("Aperçu arborescence")
        self.hierarchy_button.setObjectName("secondary")
        self.hierarchy_button.clicked.connect(self.open_hierarchy_preview)
        actions.addWidget(self.hierarchy_button)
        self.search_button = QPushButton("Recherche rapide")
        self.search_button.setObjectName("secondary")
        self.search_button.clicked.connect(self.open_search)
        actions.addWidget(self.search_button)
        actions.addStretch()
        self.rules_button = QPushButton("Règles")
        self.rules_button.setObjectName("secondary")
        self.rules_button.clicked.connect(self.open_rules)
        actions.addWidget(self.rules_button)
        root.addLayout(actions)

        settings_row = QHBoxLayout()
        self.auto_checkbox = QCheckBox("Autoriser le classement automatique pendant la surveillance (les cas ambigus vont dans À trier)")
        self.auto_checkbox.stateChanged.connect(self.set_auto_mode)
        settings_row.addWidget(self.auto_checkbox)
        settings_row.addStretch()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Copier l’original (recommandé)", "Déplacer l’original"])
        settings_row.addWidget(QLabel("Action :"))
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
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
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
        self.statusBar().showMessage("Choisis un dossier à surveiller pour commencer.")
        self.update_stats()

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
        CONFIG_FILE.write_text(json.dumps({"source": self.source_edit.text(), "destination": self.destination_edit.text()}, ensure_ascii=False, indent=2), encoding="utf-8")
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
        source = Path(self.source_edit.text().strip()).expanduser()
        destination = Path(self.destination_edit.text().strip()).expanduser()
        if not source or not destination or str(source) == "." or str(destination) == ".":
            QMessageBox.warning(self, "Dossiers requis", "Choisis un dossier à surveiller et un dossier de classement.")
            return None
        if not source.exists() or not source.is_dir():
            QMessageBox.warning(self, "Dossier invalide", "Le dossier à surveiller n’existe pas.")
            return None
        if source.resolve() == destination.resolve():
            QMessageBox.warning(self, "Dossiers identiques", "Le dossier de classement doit être différent du dossier surveillé.")
            return None
        self._save_config()
        return source.resolve(), destination.resolve()

    def scan_existing(self):
        paths = self.folder_paths()
        if not paths or (self.scan_thread and self.scan_thread.isRunning()):
            return
        source, destination = paths
        self.scan_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage("Analyse du dossier et du contenu des fichiers en cours…")
        self.scan_thread = ScanWorker(source, destination, self.classifier, self.cache)
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
                if not path.is_file() or path.is_symlink():
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
                    classification = classify_cached(self.classifier, self.cache, path)
                    target_dir, target, reason = build_destination(destination, classification, path.suffix, path.stem)
                    item = PlanItem(path, classification, target_dir, target, destination_root=destination, destination_reason=reason)
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
        self.explain.setPlainText(f"Pourquoi cette proposition ?\n{item.classification.reason}\n\nAperçu local du contenu :\n{preview}\n\nDestination :\n{item.destination_file}\n\nArborescence : {item.destination_reason or 'création ou réutilisation déterminée pendant l’analyse.'}")

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
        if QMessageBox.question(self, "Autoriser le classement", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.execute_items(items)

    def execute_items(self, items):
        if self.apply_thread and self.apply_thread.isRunning():
            return
        mode = "Déplacer l’original" if self.mode_combo.currentIndex() == 1 else "Copier l’original"
        self.approve_button.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.apply_thread = ApplyWorker(items, mode)
        self.apply_thread.progress.connect(lambda value, name: (self.progress.setValue(value), self.statusBar().showMessage(f"Classement : {name}")))
        self.apply_thread.completed.connect(self.on_apply_completed)
        self.apply_thread.failed.connect(self.on_worker_failed)
        self.apply_thread.start()

    def on_apply_completed(self, results):
        self.approve_button.setEnabled(True)
        self.progress.setVisible(False)
        keys = set()
        log_entries = []
        items_by_source = {str(item.source): item for item in self.model.items}
        for result in results:
            if isinstance(result, dict):
                source = result["source"]
                item = items_by_source.get(source)
                keys.add(item.key if item else source)
                log_entries.append(result)
                target = Path(result["target"])
                if target.exists() and item:
                    self.search_index.upsert(target, item.classification, "classé", item.hierarchy_label)
                if result.get("operation") == "move":
                    self.search_index.remove_missing()
        self.save_history(log_entries)
        self.model.remove_items(keys)
        self.statusBar().showMessage(f"{len(log_entries)} fichier(s) classé(s) avec succès.")
        self.update_badge()

    def save_history(self, entries):
        history = []
        if LOG_FILE.exists():
            try:
                history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                history = []
        history.extend(entries)
        LOG_FILE.write_text(json.dumps(history[-1000:], ensure_ascii=False, indent=2), encoding="utf-8")

    def undo_last(self):
        if not LOG_FILE.exists():
            QMessageBox.information(self, "Aucune opération", "Aucune opération récente n’est disponible pour être annulée.")
            return
        try:
            history = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            history = []
        if not history:
            QMessageBox.information(self, "Aucune opération", "Aucune opération récente n’est disponible pour être annulée.")
            return
        last = history[-1]
        target = Path(last.get("target", ""))
        source = Path(last.get("source", ""))
        if not target.exists():
            QMessageBox.warning(self, "Opération introuvable", "Le fichier classé n’existe plus à sa destination actuelle.")
            return
        if QMessageBox.question(self, "Annuler le classement", f"Restaurer « {target.name} » ?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            if last.get("operation") == "move":
                source.parent.mkdir(parents=True, exist_ok=True)
                restored = source if not source.exists() else source.with_name(f"{source.stem} (restauré){source.suffix}")
                shutil.move(str(target), str(restored))
            else:
                target.unlink()
            self.search_index.remove_missing()
            history.pop()
            LOG_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
            self.statusBar().showMessage("Dernière opération annulée.")
        except OSError as exc:
            QMessageBox.critical(self, "Annulation impossible", str(exc))

    def clear_queue(self):
        if not self.model.items:
            return
        if QMessageBox.question(self, "Vider la file", "Retirer toutes les propositions sans modifier les fichiers ?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            for item in self.model.items:
                self.search_index.delete_path(item.source)
            self.model.set_items([])
            self.statusBar().showMessage("File de classement vidée. Aucun fichier n’a été modifié.")
            self.update_badge()

    def closeEvent(self, event):
        self.watching = False
        self._stop_watch_observer()
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.quit()
            self.scan_thread.wait(1500)
        if self.apply_thread and self.apply_thread.isRunning():
            self.apply_thread.quit()
            self.apply_thread.wait(1500)
        super().closeEvent(event)

    def open_duplicate_scan(self):
        paths = self.folder_paths()
        if not paths:
            return
        source, destination = paths
        dialog = DuplicateDialog([source, destination], self)
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
