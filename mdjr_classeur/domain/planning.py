from __future__ import annotations

import re
from pathlib import Path

from ..classifier import Classification, clean_filename, fold


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


def build_destination(root: Path, classification: Classification, source_suffix: str, source_stem: str, name_stem: str | None = None) -> tuple[Path, Path, str]:
    requested_levels = list(classification.hierarchy) if classification.hierarchy else [classification.subject or "À trier", classification.category or "Autre"]
    levels: list[str] = []
    for level in requested_levels:
        cleaned = clean_filename(level, "Autre")
        if cleaned not in levels and cleaned not in {"À trier", "Autre"}:
            levels.append(cleaned)
    if not levels:
        levels = ["À trier", "Autre"]
    current = root
    reasons: list[str] = []
    for level in levels[:5]:
        current, reason = reuse_existing_folder(current, level)
        reasons.append(f"{level} : {reason}")
    title = clean_filename(name_stem or classification.title or source_stem, "Document")
    return current, (current / title).with_suffix(source_suffix.lower()), "; ".join(reasons)
