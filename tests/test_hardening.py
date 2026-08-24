from pathlib import Path
from zipfile import ZipFile

from mdjr_classeur.classifier import Classification, LocalClassifier
from mdjr_classeur.dedupe import scan_duplicates, duplicate_victims
from mdjr_classeur.search_index import SearchIndex


def test_xlsx_content_is_extracted(tmp_path: Path):
    path = tmp_path / "notes.xlsx"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<row><c><v>Attestation de scolarité universitaire</v></c></row>"
            "</worksheet>",
        )
    result = LocalClassifier().classify(path)
    assert result.category == "Administratif"
    assert result.content_status == "contenu lu"


def test_search_fallback_keeps_and_semantics(tmp_path: Path):
    index = SearchIndex(tmp_path / "search.sqlite3")
    index._fts_enabled = False
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("physique electromagnetisme", encoding="utf-8")
    second.write_text("physique seulement", encoding="utf-8")
    first_classification = Classification("Physique", "Cours", 90, "test", extracted_preview="physique electromagnetisme", title="Cours de physique")
    second_classification = Classification("Physique", "Cours", 90, "test", extracted_preview="physique seulement", title="Cours de physique")
    index.upsert(first, first_classification)
    index.upsert(second, second_classification)
    results = index.search("physique electromagnetisme")
    assert [record.path for record in results] == [str(first.resolve())]
    index.close()


def test_changed_duplicate_is_not_selected_for_action(tmp_path: Path):
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("identique", encoding="utf-8")
    second.write_text("identique", encoding="utf-8")
    report = scan_duplicates([tmp_path])
    assert report.total_file_duplicates == 1
    second.write_text("modifie", encoding="utf-8")
    assert second not in duplicate_victims(report)
