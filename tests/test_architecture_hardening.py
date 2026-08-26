from pathlib import Path

import pytest

from mdjr_classeur.application.plan import PlanEditService
from mdjr_classeur.domain.models import PlanItem
from mdjr_classeur.domain.paths import FolderPairError, resolve_folder_pair
from mdjr_classeur.infrastructure.filesystem import FileOperationService
from mdjr_classeur.classifier import Classification


def test_folder_pair_rejects_nested_paths(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(FolderPairError):
        resolve_folder_pair(source, source / "destination")


def test_plan_edit_service_rejects_path_separator(tmp_path: Path):
    source = tmp_path / "document.txt"
    source.write_text("cours de physique", encoding="utf-8")
    classification = Classification("Physique", "Cours", 80, "test", title="Cours")
    item = PlanItem(source, classification, tmp_path / "Physique", tmp_path / "Physique" / "Cours.txt", destination_root=tmp_path / "output")
    with pytest.raises(ValueError):
        PlanEditService().edit(item, "subject", "Physique/secret")


def test_file_operation_service_supports_internal_move_mode(tmp_path: Path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "output"
    source.write_text("contenu", encoding="utf-8")
    classification = Classification("Physique", "Cours", 80, "test", title="Cours")
    item = PlanItem(source, classification, destination, destination / "Cours.txt", destination_root=destination)
    results = FileOperationService().execute([item], "move")
    assert results[0]["operation"] == "move"
    assert not source.exists()
    assert item.destination_file.exists()
