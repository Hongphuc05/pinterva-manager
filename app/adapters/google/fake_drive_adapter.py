from __future__ import annotations

import re

from app.adapters.google.models import DriveVerifyResult

_DRIVE_ID_PATTERN = re.compile(r"/d/([a-zA-Z0-9_-]+)")


class FakeDriveAdapter:
    def __init__(self, known_file_ids: set[str]):
        self._known_file_ids = known_file_ids

    def verify_url(self, drive_url: str) -> DriveVerifyResult:
        match = _DRIVE_ID_PATTERN.search(drive_url)
        if match is None:
            return DriveVerifyResult(success=False, error_class="VALIDATION")
        file_id = match.group(1)
        exists = file_id in self._known_file_ids
        return DriveVerifyResult(success=True, exists=exists, accessible=exists)
