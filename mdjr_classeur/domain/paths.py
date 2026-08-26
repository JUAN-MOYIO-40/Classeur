from __future__ import annotations

from pathlib import Path


class FolderPairError(ValueError):
    """Configuration source/destination impossible ou dangereuse."""


def resolve_folder_pair(source: Path, destination: Path) -> tuple[Path, Path]:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise FolderPairError("Le dossier source n’existe pas ou n’est pas un dossier.")
    if destination.exists() and not destination.is_dir():
        raise FolderPairError("Le dossier destination existe déjà mais n’est pas un dossier.")
    if source == destination:
        raise FolderPairError("Les dossiers source et destination doivent être différents.")
    if source in destination.parents or destination in source.parents:
        raise FolderPairError("Les dossiers source et destination ne doivent pas être imbriqués.")
    return source, destination
