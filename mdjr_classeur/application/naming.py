from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..classifier import Classification, clean_filename, fold


@dataclass(frozen=True)
class FilenameProposal:
    stem: str
    reason: str
    confidence: int


class FilenameProposalService:
    """Produit des noms descriptifs sans prétendre résumer un texte inconnu."""

    GENERIC_TITLES = {"document", "cours", "notes", "page", "untitled", "sans titre"}
    FORBIDDEN_TITLE_MARKERS = (
        "date de naissance", "lieu de naissance", "né le", "nee le", "nom de naissance",
        "nom :", "prénom :", "prenom :", "matricule", "numéro de sécurité", "numero de securite",
        "nationalité", "nationalite", "sexe :", "adresse :", "téléphone :", "telephone :",
        "email :", "e-mail :", "date d'expiration", "date d expiration",
    )

    @classmethod
    def _is_safe_title(cls, value: str) -> bool:
        folded = fold(value)
        if not folded or folded in {fold(item) for item in cls.GENERIC_TITLES}:
            return False
        if any(marker in folded for marker in cls.FORBIDDEN_TITLE_MARKERS):
            return False
        tokens = folded.split()
        if len(tokens) <= 2 and sum(char.isdigit() for char in value) >= max(4, len(value) // 3):
            return False
        if re.fullmatch(r"[\d\s./_-]+", value):
            return False
        return len(tokens) >= 2 or any(char.isalpha() for char in value)

    def propose(self, path: Path, classification: Classification, content: str) -> FilenameProposal:
        original = clean_filename(path.stem, "Document")
        detected = clean_filename(classification.title or "", "")
        parts: list[str] = []
        if classification.year and classification.year.casefold() not in fold(detected):
            parts.append(classification.year)
        for value in (classification.subject, classification.topic, classification.category):
            cleaned = clean_filename(value, "")
            if cleaned and cleaned not in {"À trier", "Autre"} and fold(cleaned) not in fold(" ".join(parts)):
                parts.append(cleaned)
        detected_is_useful = bool(detected) and len(fold(detected)) >= 5 and self._is_safe_title(detected)
        if detected_is_useful:
            parts.append(detected)
        elif content.strip():
            first_line = next((re.sub(r"\s+", " ", line).strip() for line in content.splitlines() if line.strip()), "")
            if first_line and len(first_line) >= 8 and self._is_safe_title(first_line):
                parts.append(clean_filename(first_line[:90], original))
        if not parts:
            return FilenameProposal(original, "nom d’origine conservé : aucun titre fiable détecté", 25)
        unique: list[str] = []
        seen: set[str] = set()
        for part in parts:
            key = fold(part)
            if key and key not in seen:
                seen.add(key)
                unique.append(part)
        stem = clean_filename(" - ".join(unique), original)
        if stem.casefold() == original.casefold():
            return FilenameProposal(original, "nom d’origine conservé : proposition identique", 35)
        confidence = 82 if detected_is_useful and content.strip() else 62 if content.strip() else 42
        reason = "titre détecté dans le contenu et contexte de classement" if detected_is_useful and content.strip() else "contexte de classement et première ligne lisible"
        return FilenameProposal(stem, reason, confidence)
