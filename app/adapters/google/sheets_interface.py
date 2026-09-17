from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.adapters.google.models import ExportResult


@runtime_checkable
class SheetsAdapter(Protocol):
    def export_snapshot(
        self, rows: list[dict[str, str]], sheet_id: str, tab_name: str, exported_at: datetime
    ) -> ExportResult: ...
