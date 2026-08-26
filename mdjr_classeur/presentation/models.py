from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ..domain.models import PlanItem
from ..application.plan import PlanEditService
from ..i18n import tr


class PlanModel(QAbstractTableModel):
    headers = ["Fichier original", "Nom proposé", "Matière", "Nature", "Arborescence", "Confiance", "Lecture", "Destination", "État"]

    def __init__(self, plan_service: PlanEditService | None = None):
        super().__init__()
        self.plan_service = plan_service or PlanEditService()
        self.items: list[PlanItem] = []
        self.checked: set[str] = set()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 9

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        review = tr("À vérifier") if item.classification.needs_review else tr("Proposition fiable")
        proposed = item.suggested_name or item.destination_file.stem or item.source.stem
        values = [item.source.name, f"{proposed}{item.source.suffix}", item.classification.subject, item.classification.category, item.hierarchy_label, f"{item.confidence} % - {review}", tr(item.classification.content_status or "non disponible"), str(item.destination_file), tr(item.status)]
        if role in (Qt.DisplayRole, Qt.EditRole):
            return values[index.column()]
        if role == Qt.CheckStateRole and index.column() == 0:
            return Qt.Checked if item.key in self.checked else Qt.Unchecked
        if role == Qt.ForegroundRole and index.column() == 5:
            return QColor("#159570" if item.confidence >= 75 else "#cc8a20" if item.confidence >= 45 else "#d9534f")
        if role == Qt.ToolTipRole:
            proposed = item.suggested_name or item.destination_file.stem or item.source.stem
            identity = "empreinte SHA-256 calculée" if item.sha256 else "empreinte indisponible"
            return f"{item.rename_reason or 'Nom d’origine conservé'} | Confiance nom : {item.rename_confidence} % | {identity}"
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
        if role == Qt.EditRole and index.column() in (2, 3):
            text = str(value).strip() or (item.classification.subject if index.column() == 2 else item.classification.category)
            field = "subject" if index.column() == 2 else "category"
            try:
                self.plan_service.edit(item, field, text)
            except ValueError:
                return False
            self.dataChanged.emit(index, self.index(index.row(), 8), [Qt.DisplayRole, Qt.EditRole])
            return True
        return False

    def flags(self, index):
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemIsUserCheckable
        if index.column() in (2, 3):
            flags |= Qt.ItemIsEditable
        return flags

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return tr(self.headers[section])
        return None

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
