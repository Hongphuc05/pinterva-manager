from __future__ import annotations

from pydantic import BaseModel

from app.adapters.errors import ErrorClass


class AdapterResult(BaseModel):
    success: bool
    evidence: dict = {}
    error_class: ErrorClass | None = None
    retryable: bool = False
