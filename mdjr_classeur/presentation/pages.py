from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QProgressBar, QPushButton,
    QSplitter, QTableView, QTextEdit, QVBoxLayout, QWidget,
)

from ..i18n import tr


# ---------------------------------------------------------------------------
# Sidebar Navigation
# ---------------------------------------------------------------------------

class SidebarButton(QPushButton):
    """Navigation button styled as a sidebar tab with icon + label."""

    def __init__(self, icon_char: str, label: str, parent=None):
        super().__init__(parent)
        self.icon_char = icon_char
        self.label_text = label
        self.setText(f"  {icon_char}   {label}")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(44)
        self.setStyleSheet("")

    def set_active(self, active: bool):
        self.setChecked(active)


class Sidebar(QFrame):
    """Left navigation sidebar with icon buttons."""
    page_selected = Signal(int)

    NAV_ITEMS = [
        ("⌂", "Dashboard"),
        ("⤓", "Import"),
        ("☰", "Documents"),
        ("⌕", "Recherche"),
        ("⚙", "Paramètres"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(200)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 16, 8, 16)
        layout.setSpacing(4)

        logo_label = QLabel("Classeur")
        logo_label.setObjectName("sidebarLogo")
        logo_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo_label)
        layout.addSpacing(20)

        self.buttons: list[SidebarButton] = []
        for i, (icon, label) in enumerate(self.NAV_ITEMS):
            btn = SidebarButton(icon, tr(label))
            btn.clicked.connect(lambda checked, idx=i: self._on_click(idx))
            layout.addWidget(btn)
            self.buttons.append(btn)

        layout.addStretch()

        version_label = QLabel("v3.0")
        version_label.setObjectName("sidebarVersion")
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

        self._select(0)

    def _on_click(self, index: int):
        self._select(index)
        self.page_selected.emit(index)

    def _select(self, index: int):
        for i, btn in enumerate(self.buttons):
            btn.set_active(i == index)

    def select_page(self, index: int):
        self._select(index)
        self.page_selected.emit(index)


# ---------------------------------------------------------------------------
# Dashboard Page
# ---------------------------------------------------------------------------

class StatCard(QFrame):
    """Single stat card with value + caption."""

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.value_label = QLabel("0")
        self.value_label.setObjectName("statValue")
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("statCaption")
        layout.addWidget(self.value_label)
        layout.addWidget(self.caption_label)

    def set_value(self, text: str):
        self.value_label.setText(text)


class DashboardPage(QWidget):
    """Overview page with stats and quick actions."""
    scan_requested = Signal()
    watch_requested = Signal()
    search_requested = Signal()
    duplicate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 20)
        layout.setSpacing(20)

        header = QLabel(tr("Tableau de bord"))
        header.setObjectName("pageTitle")
        layout.addWidget(header)

        subtitle = QLabel(tr("Vue d'ensemble de votre espace documentaire"))
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)
        self.pending_card = StatCard(tr("fichiers en attente"))
        self.indexed_card = StatCard(tr("documents indexés"))
        self.confidence_card = StatCard(tr("confiance moyenne"))
        self.duplicates_card = StatCard(tr("doublons détectés"))
        for card in (self.pending_card, self.indexed_card, self.confidence_card, self.duplicates_card):
            stats_row.addWidget(card, 1)
        layout.addLayout(stats_row)

        actions_frame = QFrame()
        actions_frame.setObjectName("quickActions")
        actions_layout = QVBoxLayout(actions_frame)
        actions_layout.setContentsMargins(20, 16, 20, 16)

        actions_title = QLabel(tr("Actions rapides"))
        actions_title.setObjectName("sectionTitle")
        actions_layout.addWidget(actions_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self.scan_btn = QPushButton(tr("Analyser les fichiers"))
        self.scan_btn.clicked.connect(self.scan_requested)
        btn_row.addWidget(self.scan_btn)

        self.watch_btn = QPushButton(tr("Surveillance"))
        self.watch_btn.setObjectName("secondary")
        self.watch_btn.clicked.connect(self.watch_requested)
        btn_row.addWidget(self.watch_btn)

        self.search_btn = QPushButton(tr("Rechercher"))
        self.search_btn.setObjectName("secondary")
        self.search_btn.clicked.connect(self.search_requested)
        btn_row.addWidget(self.search_btn)

        self.dup_btn = QPushButton(tr("Scanner les doublons"))
        self.dup_btn.setObjectName("secondary")
        self.dup_btn.clicked.connect(self.duplicate_requested)
        btn_row.addWidget(self.dup_btn)

        btn_row.addStretch()
        actions_layout.addLayout(btn_row)
        layout.addWidget(actions_frame)

        # Status section
        self.status_frame = QFrame()
        self.status_frame.setObjectName("statusPanel")
        status_layout = QVBoxLayout(self.status_frame)
        status_layout.setContentsMargins(20, 16, 20, 16)

        self.status_badge = QLabel("●  " + tr("Surveillance inactive"))
        self.status_badge.setObjectName("statusBadge")
        status_layout.addWidget(self.status_badge)

        self.activity_label = QLabel(tr("Aucune activité récente"))
        self.activity_label.setObjectName("activityLabel")
        self.activity_label.setWordWrap(True)
        status_layout.addWidget(self.activity_label)

        self.ocr_label = QLabel()
        self.ocr_label.setObjectName("activityLabel")
        self.ocr_label.setWordWrap(True)
        status_layout.addWidget(self.ocr_label)
        layout.addWidget(self.status_frame)

        layout.addStretch()

    def update_stats(self, pending: int, indexed: int, confidence: int, duplicates: int):
        self.pending_card.set_value(str(pending))
        self.indexed_card.set_value(str(indexed))
        self.confidence_card.set_value(f"{confidence} %")
        self.duplicates_card.set_value(str(duplicates))

    def set_watch_active(self, active: bool):
        if active:
            self.status_badge.setText("●  " + tr("Surveillance active"))
            self.status_badge.setStyleSheet("color: #22c55e; font-weight: 700; font-size: 14px;")
            self.watch_btn.setText(tr("Arrêter la surveillance"))
        else:
            self.status_badge.setText("●  " + tr("Surveillance inactive"))
            self.status_badge.setStyleSheet("color: #eab308; font-weight: 700; font-size: 14px;")
            self.watch_btn.setText(tr("Surveillance"))

    def set_activity(self, message: str):
        self.activity_label.setText(message)


# ---------------------------------------------------------------------------
# Import Page
# ---------------------------------------------------------------------------

class DropZone(QFrame):
    """Drag-and-drop area for importing files."""
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(180)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        icon = QLabel("⤓")
        icon.setObjectName("dropIcon")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        label = QLabel(tr("Glissez vos fichiers ou dossiers ici"))
        label.setObjectName("dropLabel")
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)

        sublabel = QLabel(tr("PDF, DOCX, XLSX, images (JPG, PNG, TIFF…) et autres"))
        sublabel.setObjectName("dropSublabel")
        sublabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(sublabel)

        self._hovering = False

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._hovering = True
            self.setProperty("hovering", True)
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event):
        self._hovering = False
        self.setProperty("hovering", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self._hovering = False
        self.setProperty("hovering", False)
        self.style().unpolish(self)
        self.style().polish(self)
        paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))
        if paths:
            self.files_dropped.emit(paths)


class ImportPage(QWidget):
    """File import page with drag-drop and folder selection."""
    source_changed = Signal(str)
    destination_changed = Signal(str)
    scan_requested = Signal()
    watch_toggled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 20)
        layout.setSpacing(20)

        header = QLabel(tr("Import de documents"))
        header.setObjectName("pageTitle")
        layout.addWidget(header)

        # Folder selection
        folders_frame = QFrame()
        folders_frame.setObjectName("foldersFrame")
        folders_layout = QVBoxLayout(folders_frame)
        folders_layout.setContentsMargins(20, 16, 20, 16)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel(tr("Dossier à organiser")))
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText(tr("Dossier contenant les fichiers à organiser…"))
        self.source_edit.textChanged.connect(self.source_changed)
        source_row.addWidget(self.source_edit, 1)
        source_btn = QPushButton(tr("Parcourir"))
        source_btn.setObjectName("secondary")
        source_btn.clicked.connect(self._choose_source)
        source_row.addWidget(source_btn)
        folders_layout.addLayout(source_row)

        # Destination row (advanced — hidden by default, destination = source)
        self._dest_widget = QWidget()
        dest_inner = QHBoxLayout(self._dest_widget)
        dest_inner.setContentsMargins(0, 0, 0, 0)
        dest_inner.addWidget(QLabel(tr("Dossier de classement")))
        self.destination_edit = QLineEdit()
        self.destination_edit.setPlaceholderText(tr("Par défaut : même dossier que la source"))
        self.destination_edit.textChanged.connect(self.destination_changed)
        dest_inner.addWidget(self.destination_edit, 1)
        dest_btn = QPushButton(tr("Parcourir"))
        dest_btn.setObjectName("secondary")
        dest_btn.clicked.connect(self._choose_destination)
        dest_inner.addWidget(dest_btn)
        folders_layout.addWidget(self._dest_widget)
        self._dest_widget.setVisible(False)

        self._advanced_toggle = QPushButton(tr("Destination séparée…"))
        self._advanced_toggle.setObjectName("link")
        self._advanced_toggle.setFlat(True)
        self._advanced_toggle.setCursor(Qt.PointingHandCursor)
        self._advanced_toggle.clicked.connect(self._toggle_destination)
        folders_layout.addWidget(self._advanced_toggle)
        layout.addWidget(folders_frame)

        # Drop zone
        self.drop_zone = DropZone()
        layout.addWidget(self.drop_zone)

        # Actions
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.scan_button = QPushButton(tr("Analyser les fichiers existants"))
        self.scan_button.clicked.connect(self.scan_requested)
        actions.addWidget(self.scan_button)

        self.watch_button = QPushButton(tr("Démarrer la surveillance"))
        self.watch_button.clicked.connect(self.watch_toggled)
        actions.addWidget(self.watch_button)

        actions.addStretch()

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(tr("Copier (recommandé)"), "copy")
        self.mode_combo.addItem(tr("Déplacer"), "move")
        actions.addWidget(QLabel(tr("Mode :")))
        actions.addWidget(self.mode_combo)
        layout.addLayout(actions)

        self.auto_checkbox = QCheckBox(tr("Classement automatique (les cas ambigus restent à vérifier)"))
        layout.addWidget(self.auto_checkbox)

        # Progress
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        layout.addStretch()

    def _toggle_destination(self):
        visible = not self._dest_widget.isVisible()
        self._dest_widget.setVisible(visible)
        self._advanced_toggle.setText(
            tr("Masquer la destination") if visible else tr("Destination séparée…")
        )
        if not visible:
            self.destination_edit.clear()

    def _choose_source(self):
        chosen = QFileDialog.getExistingDirectory(self, tr("Choisir le dossier à organiser"))
        if chosen:
            self.source_edit.setText(chosen)

    def _choose_destination(self):
        chosen = QFileDialog.getExistingDirectory(self, tr("Choisir le dossier de classement"))
        if chosen:
            self.destination_edit.setText(chosen)


# ---------------------------------------------------------------------------
# Documents Page
# ---------------------------------------------------------------------------

class ReviewPanel(QFrame):
    """Panneau de détail pour un fichier sélectionné dans le Review Center."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel(tr("Détail du fichier"))
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.agent_label = QLabel()
        self.agent_label.setWordWrap(True)
        layout.addWidget(self.agent_label)

        self.classification_label = QLabel()
        self.classification_label.setWordWrap(True)
        layout.addWidget(self.classification_label)

        self.naming_label = QLabel()
        self.naming_label.setWordWrap(True)
        layout.addWidget(self.naming_label)

        self.destination_label = QLabel()
        self.destination_label.setWordWrap(True)
        layout.addWidget(self.destination_label)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setPlaceholderText(tr("Sélectionnez un fichier pour voir le détail."))
        self.preview_text.setMaximumHeight(120)
        layout.addWidget(self.preview_text)

    def show_item(self, item):
        if item is None:
            self.agent_label.setText("")
            self.classification_label.setText("")
            self.naming_label.setText("")
            self.destination_label.setText("")
            self.preview_text.setPlainText("")
            return
        action_labels = {
            "auto_classify": "Classement automatique",
            "propose_for_review": "Proposition (à valider)",
            "hold_for_review": "En attente de validation",
        }
        action_text = action_labels.get(item.agent_action, item.agent_action)
        self.agent_label.setText(f"Agent : {action_text}\n{item.agent_reason or ''}")
        self.classification_label.setText(
            f"Matière : {item.classification.subject}  |  Catégorie : {item.classification.category}  |  "
            f"Confiance : {item.confidence} %\n{item.classification.reason}"
        )
        proposed = item.suggested_name or item.destination_file.stem or item.source.stem
        self.naming_label.setText(
            f"Nom original : {item.source.name}\n"
            f"Nom proposé : {proposed}{item.source.suffix}  ({item.rename_confidence} %)\n"
            f"{item.rename_reason or 'nom conservé'}"
        )
        self.destination_label.setText(f"Destination : {item.destination_file}\n{item.destination_reason or ''}")
        preview = item.classification.extracted_preview or tr("Aucun extrait disponible.")
        quality = item.classification.content_status or ""
        identity = item.sha256[:16] + "…" if item.sha256 else "—"
        self.preview_text.setPlainText(f"Qualité : {quality}  |  SHA-256 : {identity}\n\n{preview}")


class DocumentsPage(QWidget):
    """Review Center — centre de validation des propositions de classement."""
    approve_requested = Signal()
    clear_requested = Signal()
    undo_requested = Signal()
    history_requested = Signal()
    hierarchy_requested = Signal()

    def __init__(self, table_view: QTableView, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 20)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header = QLabel(tr("Review Center"))
        header.setObjectName("pageTitle")
        header_row.addWidget(header)
        header_row.addStretch()

        self.pending_badge = QLabel("")
        self.pending_badge.setObjectName("pendingBadge")
        header_row.addWidget(self.pending_badge)
        layout.addLayout(header_row)

        subtitle = QLabel(tr("Validez, corrigez ou rejetez les propositions de classement"))
        subtitle.setObjectName("pageSubtitle")
        layout.addWidget(subtitle)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self.filter_combo = QComboBox()
        self.filter_combo.addItems([tr("Tous"), tr("Haute confiance (≥80%)"), tr("Moyenne (50-79%)"), tr("Faible (<50%)")])
        self.filter_combo.setFixedWidth(200)
        filter_row.addWidget(QLabel(tr("Filtre :")))
        filter_row.addWidget(self.filter_combo)
        filter_row.addStretch()

        self.approve_btn = QPushButton(tr("Classer la sélection"))
        self.approve_btn.clicked.connect(self.approve_requested)
        filter_row.addWidget(self.approve_btn)

        self.approve_all_btn = QPushButton(tr("Classer tout (≥80%)"))
        self.approve_all_btn.setObjectName("secondary")
        self.approve_all_btn.clicked.connect(self._approve_high_confidence)
        filter_row.addWidget(self.approve_all_btn)
        layout.addLayout(filter_row)

        # Action bar
        actions = QHBoxLayout()
        actions.setSpacing(8)

        undo_btn = QPushButton(tr("Annuler"))
        undo_btn.setObjectName("secondary")
        undo_btn.clicked.connect(self.undo_requested)
        actions.addWidget(undo_btn)

        history_btn = QPushButton(tr("Historique"))
        history_btn.setObjectName("secondary")
        history_btn.clicked.connect(self.history_requested)
        actions.addWidget(history_btn)

        hierarchy_btn = QPushButton(tr("Arborescence"))
        hierarchy_btn.setObjectName("secondary")
        hierarchy_btn.clicked.connect(self.hierarchy_requested)
        actions.addWidget(hierarchy_btn)

        actions.addStretch()

        clear_btn = QPushButton(tr("Vider la file"))
        clear_btn.setObjectName("danger")
        clear_btn.clicked.connect(self.clear_requested)
        actions.addWidget(clear_btn)
        layout.addLayout(actions)

        # Table + Review panel
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(table_view)

        self.review_panel = ReviewPanel()
        splitter.addWidget(self.review_panel)
        splitter.setSizes([450, 220])
        layout.addWidget(splitter, 1)

        self._approve_high_confidence_cb = None

    @property
    def explain(self):
        return self.review_panel.preview_text

    def set_pending_count(self, count: int):
        if count > 0:
            self.pending_badge.setText(f"{count} " + tr("en attente"))
            self.pending_badge.setVisible(True)
        else:
            self.pending_badge.setVisible(False)

    def show_item_detail(self, item):
        self.review_panel.show_item(item)

    def _approve_high_confidence(self):
        if self._approve_high_confidence_cb:
            self._approve_high_confidence_cb()


# ---------------------------------------------------------------------------
# Search Page (integrated, no longer a popup dialog)
# ---------------------------------------------------------------------------

class SearchPage(QWidget):
    """Full-page search with results table."""
    open_file_requested = Signal(str)

    def __init__(self, search_index, parent=None):
        super().__init__(parent)
        self.search_index = search_index
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 20)
        layout.setSpacing(16)

        header = QLabel(tr("Recherche"))
        header.setObjectName("pageTitle")
        layout.addWidget(header)

        # Search bar
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(tr("Rechercher dans vos documents…"))
        self.search_input.setObjectName("searchInput")
        self.search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self.search_input, 1)

        self.status_combo = QComboBox()
        self.status_combo.addItems([tr("Tous"), "classé", "en attente"])
        self.status_combo.setFixedWidth(130)
        self.status_combo.currentIndexChanged.connect(self._do_search)
        search_row.addWidget(self.status_combo)

        search_btn = QPushButton(tr("Rechercher"))
        search_btn.clicked.connect(self._do_search)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        self.summary = QLabel("")
        self.summary.setObjectName("searchSummary")
        layout.addWidget(self.summary)

        # Results
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels([
            tr("Nom"), tr("Matière"), tr("Catégorie"), tr("Statut"), tr("Taille")
        ])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self.results_table, 1)

        # Preview
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(150)
        self.preview.setPlaceholderText(tr("Sélectionnez un résultat pour voir l'aperçu"))
        self.results_table.currentCellChanged.connect(self._show_preview)
        layout.addWidget(self.preview)

        self._results: list = []

    def _do_search(self):
        query = self.search_input.text().strip()
        status_map = {"Tous": "Tous", "classé": "classé", "en attente": "en attente"}
        status = status_map.get(self.status_combo.currentText(), "Tous")
        results = self.search_index.hybrid_search(query, status, limit=500)
        self._results = results
        self._populate(results)

    def _populate(self, results):
        from PySide6.QtWidgets import QTableWidgetItem
        self.results_table.setRowCount(len(results))
        for i, record in enumerate(results):
            self.results_table.setItem(i, 0, QTableWidgetItem(record.name))
            self.results_table.setItem(i, 1, QTableWidgetItem(record.subject))
            self.results_table.setItem(i, 2, QTableWidgetItem(record.category))
            self.results_table.setItem(i, 3, QTableWidgetItem(record.status))
            size_str = self._format_size(record.size)
            self.results_table.setItem(i, 4, QTableWidgetItem(size_str))
        count = len(results)
        self.summary.setText(f"{count} " + tr("résultat(s)") if count else tr("Aucun résultat"))

    def _show_preview(self, row, col, prev_row, prev_col):
        if 0 <= row < len(self._results):
            record = self._results[row]
            preview = record.preview[:600] if record.preview else tr("Aucun aperçu disponible")
            self.preview.setPlainText(f"{record.name}\n{record.hierarchy}\n\n{preview}")

    def _on_double_click(self, index):
        row = index.row()
        if 0 <= row < len(self._results):
            path = self._results[row].path
            self.open_file_requested.emit(path)

    def refresh_results(self):
        self._do_search()

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("o", "Ko", "Mo", "Go"):
            if size < 1024 or unit == "Go":
                return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size} o"


# ---------------------------------------------------------------------------
# Settings Page
# ---------------------------------------------------------------------------

class SettingsPage(QWidget):
    """Settings and configuration page."""
    preferences_requested = Signal()
    rules_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 20)
        layout.setSpacing(20)

        header = QLabel(tr("Paramètres"))
        header.setObjectName("pageTitle")
        layout.addWidget(header)

        # Preferences section
        prefs_frame = QFrame()
        prefs_frame.setObjectName("settingsSection")
        prefs_layout = QVBoxLayout(prefs_frame)
        prefs_layout.setContentsMargins(20, 16, 20, 16)

        prefs_title = QLabel(tr("Apparence et comportement"))
        prefs_title.setObjectName("sectionTitle")
        prefs_layout.addWidget(prefs_title)

        prefs_desc = QLabel(tr("Thème, langue, couleur d'accent, confirmations"))
        prefs_desc.setObjectName("sectionDesc")
        prefs_layout.addWidget(prefs_desc)

        prefs_btn = QPushButton(tr("Ouvrir les préférences"))
        prefs_btn.setObjectName("secondary")
        prefs_btn.clicked.connect(self.preferences_requested)
        prefs_layout.addWidget(prefs_btn, alignment=Qt.AlignLeft)
        layout.addWidget(prefs_frame)

        # Rules section
        rules_frame = QFrame()
        rules_frame.setObjectName("settingsSection")
        rules_layout = QVBoxLayout(rules_frame)
        rules_layout.setContentsMargins(20, 16, 20, 16)

        rules_title = QLabel(tr("Règles de classification"))
        rules_title.setObjectName("sectionTitle")
        rules_layout.addWidget(rules_title)

        rules_desc = QLabel(tr("Matières, catégories, domaines et mots-clés utilisés pour la classification locale"))
        rules_desc.setObjectName("sectionDesc")
        rules_layout.addWidget(rules_desc)

        rules_btn = QPushButton(tr("Modifier les règles"))
        rules_btn.setObjectName("secondary")
        rules_btn.clicked.connect(self.rules_requested)
        rules_layout.addWidget(rules_btn, alignment=Qt.AlignLeft)
        layout.addWidget(rules_frame)

        # AI Provider section
        ai_frame = QFrame()
        ai_frame.setObjectName("settingsSection")
        ai_layout = QVBoxLayout(ai_frame)
        ai_layout.setContentsMargins(20, 16, 20, 16)
        ai_layout.setSpacing(10)

        ai_title = QLabel(tr("Intelligence locale"))
        ai_title.setObjectName("sectionTitle")
        ai_layout.addWidget(ai_title)

        self.ai_status_label = QLabel()
        self.ai_status_label.setObjectName("sectionDesc")
        self.ai_status_label.setWordWrap(True)
        ai_layout.addWidget(self.ai_status_label)

        self.ai_detail_label = QLabel()
        self.ai_detail_label.setObjectName("sectionDesc")
        self.ai_detail_label.setWordWrap(True)
        ai_layout.addWidget(self.ai_detail_label)

        self.ai_system_label = QLabel()
        self.ai_system_label.setObjectName("sectionDesc")
        self.ai_system_label.setWordWrap(True)
        ai_layout.addWidget(self.ai_system_label)

        # Mode selector
        mode_row = QHBoxLayout()
        mode_label = QLabel(tr("Mode IA :"))
        self.ai_mode_combo = QComboBox()
        self.ai_mode_combo.addItem(tr("Automatique"), "auto")
        self.ai_mode_combo.addItem(tr("Heuristiques uniquement"), "heuristic_only")
        self.ai_mode_combo.addItem(tr("LLM local"), "llm_local")
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.ai_mode_combo)
        mode_row.addStretch()
        ai_layout.addLayout(mode_row)

        layout.addWidget(ai_frame)

        # Info section
        info_frame = QFrame()
        info_frame.setObjectName("settingsSection")
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(20, 16, 20, 16)

        info_title = QLabel(tr("À propos"))
        info_title.setObjectName("sectionTitle")
        info_layout.addWidget(info_title)

        info_text = QLabel(
            tr("Classeur fonctionne entièrement en local.") + "\n"
            + tr("Aucun document n'est envoyé sur Internet.") + "\n"
            + tr("Classification, OCR, recherche et indexation sont 100% offline.")
        )
        info_text.setObjectName("sectionDesc")
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        layout.addWidget(info_frame)

        layout.addStretch()

    def update_ai_status(self, provider_name: str, available_providers: list[str],
                         model_info: dict | None = None,
                         system_info: object | None = None,
                         current_mode: str = "auto"):
        has_llm = "llama-cpp-local" in available_providers
        if has_llm and model_info:
            status = tr("Disponible")
            self.ai_status_label.setText(
                f"IA locale : {status}\n"
                f"Provider actif : {provider_name}"
            )
            detail_parts = []
            if model_info.get("name"):
                detail_parts.append(f"Modèle : {model_info['name']}")
            if model_info.get("size_display"):
                detail_parts.append(f"Taille : {model_info['size_display']}")
            if model_info.get("estimated_ram_mb"):
                detail_parts.append(f"RAM estimée : ~{model_info['estimated_ram_mb']} Mo")
            detail_parts.append("Internet : non requis")
            self.ai_detail_label.setText("\n".join(detail_parts))
        else:
            self.ai_status_label.setText(
                tr("IA locale : non installée") + "\n"
                + tr("Classeur fonctionne normalement sans IA locale.")
            )
            self.ai_detail_label.setText(
                tr("L'IA locale permet d'améliorer :") + "\n"
                + tr("  - les classifications ambiguës") + "\n"
                + tr("  - les suggestions de noms") + "\n"
                + tr("  - les résumés") + "\n"
                + tr("  - les questions sur les documents") + "\n\n"
                + tr("Pour activer, placez un fichier .gguf dans :") + "\n"
                + "~/.mdjr_classeur/models/model.gguf\n"
                + tr("et installez llama-cli dans votre PATH.")
            )
        if system_info is not None:
            ram_total = getattr(system_info, "total_ram_mb", 0)
            ram_avail = getattr(system_info, "available_ram_mb", 0)
            cpu = getattr(system_info, "cpu_name", "")
            cores = getattr(system_info, "cpu_count", 0)
            has_llama = getattr(system_info, "has_llama_cli", False)
            has_kobold = getattr(system_info, "has_koboldcpp", False)
            if has_kobold:
                runtime = f"koboldcpp ({tr('détecté')})"
            elif has_llama:
                runtime = f"llama-cli ({tr('détecté')})"
            else:
                runtime = tr("absent")
            self.ai_system_label.setText(
                f"RAM : {ram_total} Mo ({ram_avail} Mo disponible)\n"
                f"CPU : {cpu} ({cores} cœurs)\n"
                f"Runtime : {runtime}"
            )
        else:
            self.ai_system_label.setText("")
        idx = self.ai_mode_combo.findData(current_mode)
        if idx >= 0:
            self.ai_mode_combo.setCurrentIndex(idx)
