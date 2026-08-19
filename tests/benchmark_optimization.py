from __future__ import annotations

import tempfile
import time
from pathlib import Path

from mdjr_classeur.cache import ClassificationCache
from mdjr_classeur.classifier import LocalClassifier
from mdjr_classeur.dedupe import scan_duplicates


def main():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source = root / "source"
        source.mkdir()
        for index in range(80):
            (source / f"TD_maths_{index}.txt").write_text(
                "Travaux dirigés de mathématiques\nIntégrales et primitives\n" + "exercice " * 30,
                encoding="utf-8",
            )
        classifier = LocalClassifier()
        cache = ClassificationCache(root / "cache.sqlite3")
        start = time.perf_counter()
        for path in source.iterdir():
            classifier.classify(path)
        cold = time.perf_counter() - start
        start = time.perf_counter()
        for path in source.iterdir():
            cached = cache.get(path, classifier.rules_version)
            if cached is None:
                cache.put(path, classifier.rules_version, classifier.classify(path))
        first_cache_fill = time.perf_counter() - start
        start = time.perf_counter()
        for path in source.iterdir():
            cache.get(path, classifier.rules_version)
        warm = time.perf_counter() - start
        report = scan_duplicates([source])
        print(f"cold_classification_seconds={cold:.4f}")
        print(f"cache_fill_seconds={first_cache_fill:.4f}")
        print(f"cache_hit_seconds={warm:.4f}")
        print(f"scanned_files={report.scanned_files}")
        print(f"duplicate_groups={len(report.file_groups)}")


if __name__ == "__main__":
    main()
