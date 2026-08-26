from pathlib import Path
from tempfile import TemporaryDirectory

from mdjr_classeur.app import ApplyWorker, ScanWorker
from mdjr_classeur.classifier import LocalClassifier

with TemporaryDirectory() as root:
    root = Path(root)
    source = root / "a_trier"
    destination = root / "classement"
    source.mkdir()
    document = source / "TD_maths_integrales.txt"
    document.write_text("TD de mathematiques sur les integrales", encoding="utf-8")

    scan = ScanWorker(source, destination, LocalClassifier())
    captured = []
    scan.completed.connect(lambda items, count: captured.extend(items))
    scan.run()
    assert len(captured) == 1
    item = captured[0]
    assert item.classification.subject == "Mathématiques"
    assert item.classification.category == "TD"

    apply = ApplyWorker([item], "Copier l’original")
    result = []
    apply.completed.connect(lambda entries: result.extend(entries))
    apply.run()
    assert result and Path(result[0]["target"]).exists()
    assert document.exists()

    second = ApplyWorker([item], "Copier l’original")
    second_result = []
    second.completed.connect(lambda entries: second_result.extend(entries))
    second.run()
    assert second_result and second_result[0]["operation"] == "duplicate"
    assert Path(second_result[0]["duplicate_of"]).exists()

print("INTEGRATION_FLOW_OK")
