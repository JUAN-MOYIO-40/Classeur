from __future__ import annotations

from pathlib import Path

from ..dedupe import DuplicateReport, delete_duplicates, quarantine_duplicates, scan_duplicates


class DuplicateService:
    """Expose les cas d’usage de doublons sans dépendre de Qt."""

    def scan(self, roots: list[Path]) -> DuplicateReport:
        return scan_duplicates(roots)

    def quarantine(self, report: DuplicateReport, quarantine_root: Path) -> list[Path]:
        return quarantine_duplicates(report, quarantine_root)

    def delete_permanently(self, report: DuplicateReport) -> int:
        return delete_duplicates(report)
