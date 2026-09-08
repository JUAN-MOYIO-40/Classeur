from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from pathlib import Path

from ..classifier import read_content
from ..domain.models import PlanItem


TEMPORARY_SUFFIXES = {".tmp", ".part", ".partial", ".crdownload", ".download", ".swp", ".lock"}


def is_ignored_file(path: Path) -> bool:
    name = path.name.casefold()
    return (
        name.startswith("~$")
        or name.startswith(".~lock.")
        or name.endswith("~")
        or path.suffix.casefold() in TEMPORARY_SUFFIXES
        or ".classeur-partial-" in name
    )


def unique_target(target: Path) -> Path:
    if not target.exists():
        return target
    for index in range(1, 10000):
        candidate = target.with_name(f"{target.stem} ({index}){target.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("Impossible de trouver un nom libre pour ce fichier.")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_text_sha256(path: Path, max_chars: int = 250_000) -> str | None:
    content = read_content(path, max_chars)
    if not content or len(content) >= max_chars:
        return None
    normalized = "\n".join(re.sub(r"\s+", " ", line).strip() for line in content.splitlines() if line.strip()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


def find_content_match(source: Path, search_root: Path, source_digest: str | None = None, source_text_digest: str | None = None) -> tuple[Path, str] | None:
    """Retourne un document identique par octets ou par texte normalisé."""
    try:
        source_stat = source.stat()
        digest = source_digest or sha256_file(source)
    except OSError:
        return None
    if not search_root.exists() or not search_root.is_dir():
        return None
    try:
        candidates = search_root.rglob("*")
    except OSError:
        return None
    for candidate in candidates:
        if not candidate.is_file() or candidate.is_symlink() or candidate.resolve() == source.resolve() or is_ignored_file(candidate):
            continue
        try:
            if candidate.stat().st_size == source_stat.st_size and sha256_file(candidate) == digest:
                return candidate, "octets identiques"
            if source_text_digest and normalized_text_sha256(candidate) == source_text_digest:
                return candidate, "texte normalisé identique"
        except OSError:
            continue
    return None


def find_exact_content_match(source: Path, search_root: Path, source_digest: str | None = None) -> Path | None:
    """Compatibilité : recherche uniquement par empreinte binaire."""
    match = find_content_match(source, search_root, source_digest)
    return match[0] if match else None


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class FileOperationService:
    """Effectue les opérations de fichiers sans connaître la fenêtre Qt."""

    def __init__(self, duplicate_lookup=None):
        self.duplicate_lookup = duplicate_lookup

    def execute(self, items: list[PlanItem], mode: str, progress=None) -> list[dict]:
        results: list[dict] = []
        batch_id = str(time.time_ns())
        total = max(1, len(items))
        for index, item in enumerate(items, start=1):
            source = item.source
            try:
                before = source.stat()
                search_root = item.destination_root or item.destination_dir
                if self.duplicate_lookup is not None:
                    duplicate_match = self.duplicate_lookup(
                        item.sha256 or "", item.normalized_text_sha256 or "", source
                    )
                else:
                    duplicate_match = find_content_match(source, search_root, item.sha256 or None, item.normalized_text_sha256 or None)
                if duplicate_match is not None:
                    duplicate, duplicate_kind = duplicate_match
                    dup_root = item.destination_root or item.destination_dir.parent
                    dup_dir = dup_root / "Doublons"
                    dup_dir.mkdir(parents=True, exist_ok=True)
                    dup_target = unique_target(dup_dir / source.name)
                    try:
                        if mode in {"move", "Déplacer l'original"}:
                            shutil.move(str(source), str(dup_target))
                            dup_op = "move"
                        else:
                            shutil.copy2(str(source), str(dup_target))
                            dup_op = "copy"
                    except (OSError, shutil.Error) as dup_exc:
                        item.status = "Échec doublon : " + str(dup_exc)
                        results.append({
                            "source": str(source),
                            "target": str(dup_target),
                            "operation": "error",
                            "error": str(dup_exc),
                            "batch_id": batch_id,
                            "timestamp": time.time(),
                        })
                        if progress:
                            progress(int(index * 100 / total), source.name)
                        continue
                    item.status = f"Doublon → Doublons/"
                    item.destination_file = dup_target
                    results.append({
                        "source": str(source),
                        "target": str(dup_target),
                        "duplicate_of": str(duplicate),
                        "duplicate_kind": duplicate_kind,
                        "operation": "duplicate",
                        "sub_operation": dup_op,
                        "timestamp": time.time(),
                        "batch_id": batch_id,
                        "source_size": before.st_size,
                        "source_mtime_ns": before.st_mtime_ns,
                    })
                    if progress:
                        progress(int(index * 100 / total), source.name)
                    continue
                item.destination_dir.mkdir(parents=True, exist_ok=True)
                target = unique_target(item.destination_file)
                if mode in {"move", "Déplacer l’original"}:
                    shutil.move(str(source), str(target))
                    operation = "move"
                else:
                    partial = target.with_name(f".classeur-partial-{os.getpid()}-{time.time_ns()}{target.suffix}")
                    try:
                        shutil.copy2(str(source), str(partial))
                        os.replace(partial, target)
                    finally:
                        partial.unlink(missing_ok=True)
                    operation = "copy"
                after = target.stat()
                item.destination_file = target
                item.status = "Classé"
                result = {
                    "source": str(source),
                    "target": str(target),
                    "operation": operation,
                    "timestamp": time.time(),
                    "batch_id": batch_id,
                    "source_size": before.st_size,
                    "source_mtime_ns": before.st_mtime_ns,
                    "target_size": after.st_size,
                    "target_mtime_ns": after.st_mtime_ns,
                }
                results.append(result)
            except (OSError, shutil.Error) as exc:
                item.status = "Échec : " + str(exc)
                results.append({
                    "source": str(source),
                    "target": str(item.destination_file),
                    "operation": "error",
                    "error": str(exc),
                    "batch_id": batch_id,
                    "timestamp": time.time(),
                })
            if progress:
                progress(int(index * 100 / total), source.name)
        return results
