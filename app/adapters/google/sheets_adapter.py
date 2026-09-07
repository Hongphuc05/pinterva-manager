from __future__ import annotations

from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.adapters.google.models import ExportResult

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsAdapter:
    def __init__(self, credentials_path: str = "credentials/google-service-account.json"):
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        self._service = build("sheets", "v4", credentials=credentials)

    def export_snapshot(
        self, rows: list[dict], sheet_id: str, exported_at: datetime
    ) -> ExportResult:
        if not rows:
            return ExportResult(success=True, rows_written=0)
        values = [list(row.values()) for row in rows]
        try:
            response = (
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=sheet_id,
                    range="A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": values},
                )
                .execute()
            )
        except HttpError as exc:
            if exc.resp.status in (403, 404):
                return ExportResult(success=False, error_class="PERMANENT_EXTERNAL")
            if exc.resp.status == 400:
                return ExportResult(success=False, error_class="VALIDATION")
            return ExportResult(success=False, error_class="TRANSIENT_NETWORK")
        except Exception:
            return ExportResult(success=False, error_class="TRANSIENT_NETWORK")
        updated = response.get("updates", {}).get("updatedRows", len(rows))
        return ExportResult(success=True, rows_written=updated)
