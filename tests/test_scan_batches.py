from pathlib import Path

from mdjr_classeur.application.services import ClassificationService, ScanService
from mdjr_classeur.cache import ClassificationCache
from mdjr_classeur.classifier import LocalClassifier


def test_scan_batches_keeps_batch_size_bounded(tmp_path: Path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    for index in range(7):
        (source / f"note_{index}.txt").write_text(f"Mathématiques exercice {index}", encoding="utf-8")

    classifier = LocalClassifier.from_json(tmp_path / "rules.json")
    service = ScanService(
        ClassificationService(classifier, ClassificationCache(tmp_path / "cache.sqlite3"))
    )
    batches = list(service.scan_batches(source, destination, batch_size=3))

    assert [len(batch) for batch in batches] == [3, 3, 1]
    assert sum(len(batch) for batch in batches) == 7
