from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ..domain.models import PlanItem
from ..domain.planning import build_destination
from ..i18n import tr


class PlanModel(QAbstractTableModel):
    headers = ["Fichier", "Matière", "Nature", "Arborescence", "Confiance", "Lecture", "Destination", "État"]

    def __init__(self):
        super().__init__()
        self.items: list[PlanItem] = []
        self.checked: set[str] = set()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()):
        return 8

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        review = tr("À vérifier") if item.classification.needs_review else tr("Proposition fiable")
        values = [item.source.name, item.classification.subject, item.classification.category, item.hierarchy_label, f"{item.confidence} % - {review}", tr(item.classification.content_status or "non disponible"), str(item.destination_file), item.status]
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
            self.dataChanged.emit(index, self.index(index.row(), 7), [Qt.DisplayRole, Qt.EditRole])
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
            return tr(self.headers[section])
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
