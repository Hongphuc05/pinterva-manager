from __future__ import annotations

from datetime import datetime

from app.adapters.google.models import ExportResult


class FakeSheetsAdapter:
    def __init__(self):
        self.rows_by_sheet: dict[tuple[str, str], list[dict[str, str]]] = {}
        self.export_calls = 0

    def export_snapshot(
        self, rows: list[dict[str, str]], sheet_id: str, tab_name: str, exported_at: datetime
    ) -> ExportResult:
        # Repeat exports replace the old snapshot instead of accumulating duplicates.
        self.export_calls += 1
        self.rows_by_sheet[(sheet_id, tab_name)] = [dict(row) for row in rows]
        return ExportResult(success=True, rows_written=len(rows))
