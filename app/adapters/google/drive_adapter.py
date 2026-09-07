from __future__ import annotations

import re

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.adapters.google.models import DriveVerifyResult

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

_DRIVE_ID_PATTERN = re.compile(r"/d/([a-zA-Z0-9_-]+)")


def _extract_file_id(drive_url: str) -> str | None:
    match = _DRIVE_ID_PATTERN.search(drive_url)
    if match:
        return match.group(1)
    if "id=" in drive_url:
        return drive_url.split("id=")[-1].split("&")[0]
    return None


class GoogleDriveAdapter:
    def __init__(self, credentials_path: str = "credentials/google-service-account.json"):
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        self._service = build("drive", "v3", credentials=credentials)

    def verify_url(self, drive_url: str) -> DriveVerifyResult:
        file_id = _extract_file_id(drive_url)
        if file_id is None:
            return DriveVerifyResult(success=False, exists=False, error_class="VALIDATION")
        try:
            self._service.files().get(fileId=file_id, fields="id,name").execute()
        except HttpError as exc:
            if exc.resp.status == 404:
                return DriveVerifyResult(success=True, exists=False, accessible=False)
            if exc.resp.status == 403:
                return DriveVerifyResult(success=True, exists=True, accessible=False)
            if exc.resp.status == 401:
                return DriveVerifyResult(success=False, error_class="AUTH")
            if exc.resp.status == 400:
                return DriveVerifyResult(success=False, error_class="VALIDATION")
            return DriveVerifyResult(success=False, error_class="TRANSIENT_NETWORK")
        except Exception:
            return DriveVerifyResult(success=False, error_class="TRANSIENT_NETWORK")
        return DriveVerifyResult(success=True, exists=True, accessible=True)
