from __future__ import annotations

from app.adapters.google.drive_adapter import _extract_file_id
from app.adapters.google.models import DriveVerifyResult


class FakeDriveAdapter:
    def __init__(self, known_file_ids: set[str]):
        self._known_file_ids = known_file_ids

    def verify_url(self, drive_url: str) -> DriveVerifyResult:
        file_id = _extract_file_id(drive_url)
        if file_id is None:
            return DriveVerifyResult(success=False, error_class="VALIDATION")
        exists = file_id in self._known_file_ids
        return DriveVerifyResult(success=True, exists=exists, accessible=exists)
