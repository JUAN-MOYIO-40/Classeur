from pathlib import Path

from mdjr_classeur.application.agent import AgentLedger


def test_ledger_skips_unchanged_completed_file(tmp_path: Path):
    document = tmp_path / "document.txt"
    document.write_text("contenu", encoding="utf-8")
    ledger = AgentLedger(tmp_path / "agent.sqlite3")
    try:
        assert ledger.needs_processing(document)
        assert ledger.start(document)
        target = tmp_path / "classe" / "document.txt"
        target.parent.mkdir()
        target.write_text("contenu", encoding="utf-8")
        ledger.finish(document, target=target)
        assert not ledger.needs_processing(document)
        assert ledger.counts()["done"] == 1
    finally:
        ledger.close()


def test_ledger_reopens_interrupted_work(tmp_path: Path):
    document = tmp_path / "document.txt"
    document.write_text("contenu", encoding="utf-8")
    ledger = AgentLedger(tmp_path / "agent.sqlite3")
    assert ledger.start(document)
    assert ledger.recover_interrupted() == 1
    assert ledger.needs_processing(document)
    ledger.close()


def test_ledger_detects_modified_file(tmp_path: Path):
    document = tmp_path / "document.txt"
    document.write_text("version 1", encoding="utf-8")
    ledger = AgentLedger(tmp_path / "agent.sqlite3")
    try:
        ledger.start(document)
        target = tmp_path / "classe" / "document.txt"
        target.parent.mkdir()
        target.write_text("version 1", encoding="utf-8")
        ledger.finish(document, target=target)
        document.write_text("version 2", encoding="utf-8")
        assert ledger.needs_processing(document)
    finally:
        ledger.close()
