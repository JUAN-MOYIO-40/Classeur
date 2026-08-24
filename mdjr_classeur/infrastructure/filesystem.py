from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

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

    def execute(self, items: list[PlanItem], mode: str, progress=None) -> list[dict]:
        results: list[dict] = []
        batch_id = str(time.time_ns())
        total = max(1, len(items))
        for index, item in enumerate(items, start=1):
            source = item.source
            try:
                before = source.stat()
                item.destination_dir.mkdir(parents=True, exist_ok=True)
                target = unique_target(item.destination_file)
                if mode in {"move", "Déplacer l’original"}:
                    shutil.move(str(source), str(target))
                    operation = "move"
                else:
                    partial = target.with_name(f".{target.name}.classeur-partial-{time.time_ns()}")
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
