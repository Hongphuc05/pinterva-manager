from __future__ import annotations

from datetime import datetime

from app.adapters.google.models import ExportResult


class FakeSheetsAdapter:
    def __init__(self):
        self.rows_by_sheet: dict[str, list[dict]] = {}

    def export_snapshot(
        self, rows: list[dict], sheet_id: str, exported_at: datetime
    ) -> ExportResult:
        self.rows_by_sheet.setdefault(sheet_id, []).extend(rows)
        return ExportResult(success=True, rows_written=len(rows))
