from __future__ import annotations

from app.adapters.base_models import AdapterResult


class ExportResult(AdapterResult):
    rows_written: int = 0


class DriveVerifyResult(AdapterResult):
    exists: bool = False
    accessible: bool = False
