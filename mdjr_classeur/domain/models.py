from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..classifier import Classification


@dataclass
class PlanItem:
    """Proposition métier indépendante de Qt, prête à être validée ou exécutée."""

    source: Path
    classification: Classification
    destination_dir: Path
    destination_file: Path
    status: str = "En attente"
    existing: bool = False
    destination_root: Path | None = None
    destination_reason: str = ""
    suggested_name: str = ""
    sha256: str = ""
    normalized_text_sha256: str = ""
    text_length: int = 0
    rename_reason: str = ""
    rename_confidence: int = 0
    agent_action: str = "propose_for_review"
    agent_reason: str = ""
    agent_requires_confirmation: bool = True
    human_corrected_fields: set[str] | None = None

    def __post_init__(self):
        if self.human_corrected_fields is None:
            self.human_corrected_fields = set()

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
