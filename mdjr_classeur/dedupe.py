from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


QUICK_SAMPLE_SIZE = 64 * 1024


@dataclass
class DuplicateFileGroup:
    digest: str
    size: int
    files: list[Path]

    @property
    def duplicate_count(self) -> int:
        return max(0, len(self.files) - 1)

    @property
    def recoverable_bytes(self) -> int:
        return self.size * self.duplicate_count


@dataclass
class DuplicateFolderGroup:
    signature: str
    folders: list[Path]
    file_count: int
    total_size: int

    @property
    def duplicate_count(self) -> int:
        return max(0, len(self.folders) - 1)


@dataclass
class DuplicateReport:
    file_groups: list[DuplicateFileGroup]
    folder_groups: list[DuplicateFolderGroup]
    scanned_files: int
    scanned_folders: int

    @property
    def total_file_duplicates(self) -> int:
        return sum(group.duplicate_count for group in self.file_groups)

    @property
    def total_folder_duplicates(self) -> int:
        return sum(group.duplicate_count for group in self.folder_groups)

    @property
    def recoverable_bytes(self) -> int:
        file_bytes = sum(group.recoverable_bytes for group in self.file_groups)
        folder_bytes = sum(group.total_size * group.duplicate_count for group in self.folder_groups)
        return file_bytes + folder_bytes


def _stat_key(path: Path) -> tuple[str, int, int] | None:
    try:
        stat = path.stat()
        return str(path.resolve()), stat.st_size, stat.st_mtime_ns
    except OSError:
        return None


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 complet, utilisé uniquement après filtrage par taille et empreinte rapide."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def quick_hash_file(path: Path, sample_size: int = QUICK_SAMPLE_SIZE) -> str:
    """Empreinte rapide : taille + début + fin du fichier, sans lire tout un gros fichier."""
    stat = path.stat()
    digest = hashlib.blake2b(digest_size=16)
    digest.update(str(stat.st_size).encode("ascii"))
    with path.open("rb") as handle:
        first = handle.read(sample_size)
        digest.update(first)
        if stat.st_size > sample_size:
            handle.seek(max(0, stat.st_size - sample_size))
            digest.update(handle.read(sample_size))
    return digest.hexdigest()


def _cached_digest(path: Path, cache: dict[tuple[str, int, int, str], str], quick: bool) -> str:
    key_base = _stat_key(path)
    if key_base is None:
        raise OSError(f"Fichier indisponible : {path}")
    key = (*key_base, "quick" if quick else "full")
    if key not in cache:
        cache[key] = quick_hash_file(path) if quick else hash_file(path)
    return cache[key]


def _iter_files(root: Path):
    if not root.exists() or not root.is_dir():
        return
    try:
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                yield path
    except OSError:
        return


def _folder_signature(folder: Path, digest_cache: dict[tuple[str, int, int, str], str], quick: bool) -> tuple[str, int, int] | None:
    entries: list[tuple[str, int, str]] = []
    total_size = 0
    for path in _iter_files(folder):
        try:
            relative = path.relative_to(folder).as_posix().lower()
            size = path.stat().st_size
            digest = _cached_digest(path, digest_cache, quick)
        except (OSError, ValueError):
            continue
        entries.append((relative, size, digest))
        total_size += size
    if not entries:
        return None
    entries.sort()
    raw = "\n".join(f"{name}|{size}|{digest}" for name, size, digest in entries).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), len(entries), total_size


def _unique_roots(roots: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    candidates: list[Path] = []
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved).casefold()
        if key not in seen and resolved.exists() and resolved.is_dir():
            seen.add(key)
            candidates.append(resolved)
    for candidate in sorted(candidates, key=lambda item: (len(item.parts), str(item).casefold())):
        if any(parent == candidate or parent in candidate.parents for parent in result):
            continue
        result.append(candidate)
    return result


def scan_duplicates(roots: list[Path]) -> DuplicateReport:
    """Analyse les doublons exacts avec filtrage progressif, sans modifier les fichiers."""
    roots = _unique_roots(roots)
    files_by_size: dict[int, list[Path]] = {}
    all_files: list[Path] = []
    for root in roots:
        for path in _iter_files(root):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            files_by_size.setdefault(size, []).append(path)
            all_files.append(path)

    digest_cache: dict[tuple[str, int, int, str], str] = {}
    quick_groups: dict[tuple[int, str], list[Path]] = {}
    for size, paths in files_by_size.items():
        if len(paths) < 2:
            continue
        for path in paths:
            try:
                quick_groups.setdefault((size, _cached_digest(path, digest_cache, quick=True)), []).append(path)
            except OSError:
                continue

    by_digest: dict[tuple[int, str], list[Path]] = {}
    for (size, _quick), paths in quick_groups.items():
        if len(paths) < 2:
            continue
        for path in paths:
            try:
                by_digest.setdefault((size, _cached_digest(path, digest_cache, quick=False)), []).append(path)
            except OSError:
                continue
    file_groups = [
        DuplicateFileGroup(digest, size, sorted(paths, key=lambda item: str(item).casefold()))
        for (size, digest), paths in by_digest.items() if len(paths) > 1
    ]
    file_groups.sort(key=lambda group: (-group.recoverable_bytes, str(group.files[0]).casefold()))

    folder_quick_groups: dict[str, list[tuple[Path, int, int]]] = {}
    candidate_folders: set[Path] = set()
    for root in roots:
        try:
            folders = [root, *[path for path in root.rglob("*") if path.is_dir() and not path.is_symlink()]]
        except OSError:
            folders = [root]
        for folder in folders:
            signature = _folder_signature(folder, digest_cache, quick=True)
            if signature is None:
                continue
            digest, file_count, total_size = signature
            folder_quick_groups.setdefault(digest, []).append((folder, file_count, total_size))
            candidate_folders.add(folder)

    folder_by_signature: dict[str, list[tuple[Path, int, int]]] = {}
    for _quick_signature, entries in folder_quick_groups.items():
        if len(entries) < 2:
            continue
        for folder, _file_count, _total_size in entries:
            signature = _folder_signature(folder, digest_cache, quick=False)
            if signature is None:
                continue
            digest, file_count, total_size = signature
            folder_by_signature.setdefault(digest, []).append((folder, file_count, total_size))

    folder_groups = [
        DuplicateFolderGroup(signature, sorted([entry[0] for entry in entries], key=lambda item: str(item).casefold()), entries[0][1], entries[0][2])
        for signature, entries in folder_by_signature.items() if len(entries) > 1
    ]
    folder_groups.sort(key=lambda group: (-group.total_size * group.duplicate_count, str(group.folders[0]).casefold()))
    return DuplicateReport(file_groups, folder_groups, len(all_files), len(candidate_folders))


def _unique_quarantine_target(root: Path, original: Path) -> Path:
    target = root / original.name
    if not target.exists():
        return target
    for index in range(1, 10000):
        candidate = root / f"{original.stem} ({index}){original.suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Impossible de créer un nom libre dans la quarantaine.")


def duplicate_victims(report: DuplicateReport) -> list[Path]:
    victims: list[Path] = []
    for group in report.file_groups:
        victims.extend(group.files[1:])
    for group in report.folder_groups:
        victims.extend(group.folders[1:])
    unique: list[Path] = []
    for path in sorted(set(victims), key=lambda item: (len(item.parts), str(item).casefold())):
        if any(parent == path or parent in path.parents for parent in unique if parent.is_dir()):
            continue
        unique.append(path)
    return unique


def quarantine_duplicates(report: DuplicateReport, quarantine_root: Path) -> list[Path]:
    """Déplace les copies excédentaires vers une zone réversible plutôt que de les supprimer brutalement."""
    unique = duplicate_victims(report)
    destination = quarantine_root / time.strftime("%Y%m%d-%H%M%S")
    moved: list[Path] = []
    for path in unique:
        if not path.exists():
            continue
        destination.mkdir(parents=True, exist_ok=True)
        target = _unique_quarantine_target(destination, path)
        try:
            shutil.move(str(path), str(target))
            moved.append(target)
        except OSError:
            continue
    return moved


def delete_duplicates(report: DuplicateReport) -> int:
    """Supprime définitivement les copies excédentaires après confirmation explicite de l’utilisateur."""
    removed = 0
    for path in sorted(duplicate_victims(report), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def format_bytes(value: int) -> str:
    units = ["o", "Ko", "Mo", "Go", "To"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "o" else f"{int(amount)} {unit}"
        amount /= 1024
    return f"{value} o"
