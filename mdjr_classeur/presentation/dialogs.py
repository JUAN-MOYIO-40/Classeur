from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHeaderView, QWidget,
)

from ..infrastructure.history import HistoryRepository
from ..i18n import tr
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHeaderView, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QTreeWidget, QTreeWidgetItem,
)

from ..classifier import LocalClassifier
from ..dedupe import DuplicateReport, delete_duplicates, format_bytes, quarantine_duplicates
from ..domain.models import PlanItem
from ..search_index import SearchIndex, SearchRecord
from .workers import DuplicateWorker



class PreferencesDialog(QDialog):
    def __init__(self, preferences: dict[str, object], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Préférences de Classeur"))
        self.resize(680, 460)
        self.preferences = dict(preferences)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        general = QWidget()
        general_form = QFormLayout(general)
        self.language_combo = QComboBox()
        self.language_combo.addItem(tr("Français"), "fr")
        self.language_combo.addItem(tr("English"), "en")
        current_language = str(self.preferences.get("language", "fr"))
        self.language_combo.setCurrentIndex(0 if current_language == "fr" else 1)
        general_form.addRow(tr("Langue"), self.language_combo)
        self.confirm_checkbox = QCheckBox(tr("Confirmer les actions sensibles"))
        self.confirm_checkbox.setChecked(bool(self.preferences.get("confirm_actions", True)))
        general_form.addRow("", self.confirm_checkbox)
        tabs.addTab(general, tr("Général"))

        appearance = QWidget()
        appearance_form = QFormLayout(appearance)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem(tr("Système"), "system")
        self.theme_combo.addItem(tr("Clair"), "light")
        self.theme_combo.addItem(tr("Sombre"), "dark")
        current_theme = str(self.preferences.get("theme", "system"))
        self.theme_combo.setCurrentIndex({"system": 0, "light": 1, "dark": 2}.get(current_theme, 0))
        appearance_form.addRow(tr("Thème"), self.theme_combo)

        self.accent_value = str(self.preferences.get("accent", "#1c8c70"))
        self.accent_button = QPushButton(self.accent_value)
        self.accent_button.clicked.connect(self.choose_accent)
        self._refresh_accent_button()
        appearance_form.addRow(tr("Couleur d’accent"), self.accent_button)

        background_row = QHBoxLayout()
        self.background_edit = QLineEdit(str(self.preferences.get("background", "")))
        self.background_edit.setReadOnly(True)
        self.background_edit.setPlaceholderText(tr("Aucune image"))
        background_row.addWidget(self.background_edit, 1)
        choose_background = QPushButton(tr("Choisir une image…"))
        choose_background.clicked.connect(self.choose_background)
        background_row.addWidget(choose_background)
        reset_background = QPushButton(tr("Réinitialiser"))
        reset_background.setObjectName("secondary")
        reset_background.clicked.connect(self.background_edit.clear)
        background_row.addWidget(reset_background)
        appearance_form.addRow(tr("Image de fond"), background_row)
        tabs.addTab(appearance, tr("Apparence"))

        safety = QWidget()
        safety_form = QFormLayout(safety)
        safety_form.addRow(QLabel("Les fichiers importants doivent rester sauvegardés séparément. La suppression définitive des doublons ne peut pas être annulée par Classeur."))
        tabs.addTab(safety, tr("Sécurité"))
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh_accent_button(self):
        self.accent_button.setText(self.accent_value)
        self.accent_button.setStyleSheet(f"background: {self.accent_value}; color: white; font-weight: 700;")

    def choose_accent(self):
        color = QColorDialog.getColor(QColor(self.accent_value), self, tr("Couleur d’accent"))
        if color.isValid():
            self.accent_value = color.name()
            self._refresh_accent_button()

    def choose_background(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Choisir une image…"), "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.background_edit.setText(path)

    def values(self) -> dict[str, object]:
        return {
            "language": self.language_combo.currentData(),
            "theme": self.theme_combo.currentData(),
            "accent": self.accent_value,
            "background": self.background_edit.text().strip(),
            "confirm_actions": self.confirm_checkbox.isChecked(),
        }


class HistoryDialog(QDialog):
    undo_requested = Signal()

    def __init__(self, history_repository: HistoryRepository, parent=None):
        super().__init__(parent)
        self.history_repository = history_repository
        self.setWindowTitle(tr("Historique"))
        self.resize(980, 560)
        layout = QVBoxLayout(self)
        intro = QLabel(tr("Les opérations réussies sont conservées localement. L’annulation vérifie que les fichiers n’ont pas changé."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([tr("Date"), tr("Action"), tr("Fichier source"), tr("Destination"), tr("État")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        refresh = QPushButton(tr("Actualiser"))
        refresh.clicked.connect(self.load_history)
        buttons.addWidget(refresh)
        buttons.addStretch()
        undo = QPushButton(tr("Annuler la dernière opération"))
        undo.setObjectName("secondary")
        undo.clicked.connect(self.undo_requested.emit)
        buttons.addWidget(undo)
        close_button = QPushButton(tr("Fermer"))
        close_button.setObjectName("secondary")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.load_history()

    def load_history(self):
        history = self.history_repository.load()
        self.table.setRowCount(len(history))
        for row, entry in enumerate(reversed(history)):
            action = tr("Déplacement") if entry.get("operation") == "move" else tr("Copie")
            values = [time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.get("timestamp", 0))), action, entry.get("source", ""), entry.get("target", ""), tr("Réussi")]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))

class DuplicateDialog(QDialog):
    def __init__(self, roots: list[Path], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Analyse intelligente des doublons") + " - " + tr("MDJR classeur"))
        self.resize(980, 620)
        self.roots = roots
        self.report: DuplicateReport | None = None
        self.worker: DuplicateWorker | None = None
        layout = QVBoxLayout(self)
        intro = QLabel(tr("MDJR compare le contenu réel des fichiers et la structure complète des dossiers. Rien n’est supprimé automatiquement."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.summary = QLabel(tr("Prêt à analyser les emplacements sélectionnés."))
        self.summary.setStyleSheet("font-size: 15px; font-weight: 700; color: #17324d;")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("Type"), tr("Éléments identiques"), tr("Espace récupérable"), tr("Emplacements")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        self.scan_button = QPushButton(tr("Relancer l’analyse"))
        self.scan_button.setObjectName("secondary")
        self.scan_button.clicked.connect(self.scan)
        buttons.addWidget(self.scan_button)
        self.quarantine_button = QPushButton(tr("Mettre les copies en quarantaine"))
        self.quarantine_button.setObjectName("danger")
        self.quarantine_button.setEnabled(False)
        self.quarantine_button.clicked.connect(self.quarantine)
        buttons.addWidget(self.quarantine_button)
        self.delete_button = QPushButton(tr("Supprimer définitivement"))
        self.delete_button.setObjectName("danger")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_permanently)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        close_button = QPushButton(tr("Fermer"))
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
        self.setWindowTitle(tr("Recherche rapide") + " - " + tr("MDJR classeur"))
        self.resize(1050, 650)
        layout = QVBoxLayout(self)
        heading = QLabel(tr("Recherche documentaire locale"))
        heading.setStyleSheet("font-size: 22px; font-weight: 800; color: #17324d;")
        layout.addWidget(heading)
        intro = QLabel(tr("Recherche dans les noms, matières, natures, chemins, titres et extraits de contenu. Aucun document ne quitte ton ordinateur."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        controls = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(tr("Ex. intégrales, attestation, projet web, semestre 2…"))
        self.query_edit.setClearButtonEnabled(True)
        self.query_edit.textChanged.connect(self.refresh_results)
        controls.addWidget(self.query_edit, 1)
        self.status_combo = QComboBox()
        self.status_combo.addItem(tr("Tous"), "Tous")
        self.status_combo.addItem(tr("classé"), "classé")
        self.status_combo.addItem(tr("en attente"), "en attente")
        self.status_combo.currentTextChanged.connect(self.refresh_results)
        controls.addWidget(QLabel(tr("Statut :")))
        controls.addWidget(self.status_combo)
        refresh = QPushButton(tr("Actualiser"))
        refresh.setObjectName("secondary")
        refresh.clicked.connect(self.refresh_results)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.summary = QLabel(tr("Saisis un mot-clé pour commencer."))
        self.summary.setStyleSheet("font-weight: 700; color: #47627a;")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr("Fichier"), tr("Matière"), tr("Nature"), tr("Arborescence"), tr("Statut"), tr("Emplacement")])
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
        self.preview.setPlaceholderText(tr("Sélectionne un résultat pour afficher son titre et son extrait."))
        self.table.itemSelectionChanged.connect(self.show_preview)
        layout.addWidget(self.preview)
        buttons = QHBoxLayout()
        open_button = QPushButton(tr("Ouvrir le fichier"))
        open_button.clicked.connect(self.open_selected)
        buttons.addWidget(open_button)
        folder_button = QPushButton(tr("Afficher le dossier"))
        folder_button.setObjectName("secondary")
        folder_button.clicked.connect(self.open_folder)
        buttons.addWidget(folder_button)
        buttons.addStretch()
        close_button = QPushButton(tr("Fermer"))
        close_button.setObjectName("secondary")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def refresh_results(self):
        try:
            self.records = self.index.search(self.query_edit.text(), self.status_combo.currentData() or "Tous")
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


class RulesDialog(QDialog):
    def __init__(self, classifier: LocalClassifier, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Règles intelligentes") + " - " + tr("MDJR classeur"))
        self.resize(720, 520)
        self.classifier = classifier
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("Modifie les mots-clés séparés par des virgules. Les changements restent locaux.")))
        self.subjects = QTextEdit()
        self.categories = QTextEdit()
        self.domains = QTextEdit()
        self.topics = QTextEdit()
        self.subjects.setPlainText("\n".join(f"{name}: {', '.join(words)}" for name, words in classifier.subjects.items()))
        self.categories.setPlainText("\n".join(f"{name}: {', '.join(words)}" for name, words in classifier.categories.items()))
        self.domains.setPlainText("\n".join(f"{name}: {', '.join(words)}" for name, words in classifier.domains.items()))
        self.topics.setPlainText("\n".join(f"{name}: {', '.join(words)}" for name, words in classifier.topics.items()))
        form = QFormLayout()
        form.addRow(tr("Matières"), self.subjects)
        form.addRow(tr("Natures"), self.categories)
        form.addRow(tr("Domaines"), self.domains)
        form.addRow(tr("Thèmes"), self.topics)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        def parse(text: str, section: str):
            result = {}
            errors = []
            for line_number, raw_line in enumerate(text.splitlines(), start=1):
                line = raw_line.strip()
                if not line:
                    continue
                if ":" not in line:
                    errors.append(f"{section}, ligne {line_number} : deux-points manquant")
                    continue
                name, words = (part.strip() for part in line.split(":", 1))
                if not name or not words:
                    errors.append(f"{section}, ligne {line_number} : nom ou mots-clés vide")
                    continue
                if any(char in name for char in '/\\\\:*?"<>|'):
                    errors.append(f"{section}, ligne {line_number} : nom de dossier invalide")
                    continue
                values = list(dict.fromkeys(word.strip() for word in words.split(",") if word.strip()))
                if not values:
                    errors.append(f"{section}, ligne {line_number} : aucun mot-clé valide")
                    continue
                if name in result:
                    errors.append(f"{section}, ligne {line_number} : nom répété « {name} »")
                    continue
                result[name] = values
            return result, errors

        parsed = [
            parse(self.subjects.toPlainText(), "Matières"),
            parse(self.categories.toPlainText(), "Natures"),
            parse(self.domains.toPlainText(), "Domaines"),
            parse(self.topics.toPlainText(), "Thèmes"),
        ]
        errors = [error for _values, section_errors in parsed for error in section_errors]
        if errors:
            QMessageBox.warning(self, "Règles non enregistrées", "Corrige ces lignes avant de continuer :\n\n" + "\n".join(errors[:12]))
            return
        subjects, categories, domains, topics = (values for values, _errors in parsed)
        if not all((subjects, categories, domains, topics)):
            QMessageBox.warning(self, "Règles incomplètes", "Chaque section doit contenir au moins une règle.")
            return
        self.classifier.subjects = subjects
        self.classifier.categories = categories
        self.classifier.domains = domains
        self.classifier.topics = topics
        super().accept()


class HierarchyDialog(QDialog):
    def __init__(self, items: list[PlanItem], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Aperçu de l’arborescence - MDJR classeur"))
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


