from __future__ import annotations

from pathlib import Path

from ..classifier import clean_filename
from ..domain.models import PlanItem
from ..domain.planning import build_destination


class PlanEditService:
    """Valide et applique les corrections humaines sur une proposition."""

    editable_fields = {"subject", "category"}

    def edit(self, item: PlanItem, field: str, value: str) -> None:
        if field not in self.editable_fields:
            raise ValueError("Champ de proposition non modifiable.")
        raw_value = str(value).strip()
        if any(char in raw_value for char in '/\\<>:"|?*\x00'):
            raise ValueError("Le libellé ne peut pas contenir de séparateur de chemin ou de caractère interdit.")
        cleaned = clean_filename(raw_value, "À trier" if field == "subject" else "Autre")
        if not cleaned or len(cleaned) > 120:
            raise ValueError("Le libellé doit contenir entre 1 et 120 caractères valides.")
        setattr(item.classification, field, cleaned)
        if item.human_corrected_fields is None:
            item.human_corrected_fields = set()
        item.human_corrected_fields.add(field)
        item.classification.hierarchy = tuple(
            part for part in (
                item.classification.year,
                item.classification.domain,
                item.classification.subject,
                item.classification.topic,
                item.classification.category,
            ) if part and part not in {"À trier", "Autre"}
        )
        root = item.destination_root or item.destination_dir.parents[1]
        item.destination_dir, item.destination_file, item.destination_reason = build_destination(
            root, item.classification, item.source.suffix, item.source.stem
        )
