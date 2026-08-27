from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class OnlineMode(StrEnum):
    LOCAL_ONLY = "local_only"
    EXCERPT_ONLY = "excerpt_only"


@dataclass(frozen=True)
class OnlineAssistPolicy:
    """Politique de confidentialité avant toute assistance distante.

    Cette classe ne réalise aucun appel réseau. Elle décide uniquement si un
    extrait peut être préparé pour un adaptateur distant ultérieur.
    """

    mode: OnlineMode = OnlineMode.LOCAL_ONLY
    consent_given: bool = False
    max_excerpt_chars: int = 12_000
    max_file_size_bytes: int = 25 * 1024 * 1024

    @property
    def enabled(self) -> bool:
        return self.mode != OnlineMode.LOCAL_ONLY and self.consent_given

    def can_send(self, path: Path, excerpt: str) -> bool:
        if not self.enabled or self.mode != OnlineMode.EXCERPT_ONLY:
            return False
        try:
            if path.stat().st_size > self.max_file_size_bytes:
                return False
        except OSError:
            return False
        return bool(excerpt.strip())

    def prepare_excerpt(self, path: Path, excerpt: str) -> dict[str, str] | None:
        if not self.can_send(path, excerpt):
            return None
        cleaned = " ".join(excerpt.split())[: self.max_excerpt_chars]
        if not cleaned:
            return None
        return {
            "filename": path.name,
            "extension": path.suffix.casefold(),
            "excerpt": cleaned,
        }
