from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.adapters.google.models import DriveVerifyResult


@runtime_checkable
class DriveAdapter(Protocol):
    def verify_url(self, drive_url: str) -> DriveVerifyResult: ...
