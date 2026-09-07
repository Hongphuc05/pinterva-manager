from __future__ import annotations

from pydantic import BaseModel

from app.adapters.errors import ErrorClass


class ExportResult(BaseModel):
    success: bool
    rows_written: int = 0
    error_class: ErrorClass | None = None


class DriveVerifyResult(BaseModel):
    success: bool
    exists: bool = False
    accessible: bool = False
    error_class: ErrorClass | None = None
