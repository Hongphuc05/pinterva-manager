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
        self, rows: list[dict[str, str]], sheet_id: str, tab_name: str, exported_at: datetime
    ) -> ExportResult:
        # Quote the tab name so a name containing spaces or apostrophes cannot alter
        # the target range. RAW prevents product/order values from becoming formulas.
        quoted_tab = "'" + tab_name.replace("'", "''") + "'"
        values = [["Mã đơn", "Link DES nộp bài"]]
        values.extend([[row.get("Mã đơn", ""), row.get("Link DES nộp bài", "")] for row in rows])
        try:
            self._service.spreadsheets().values().clear(
                spreadsheetId=sheet_id,
                range=f"{quoted_tab}!A:Z",
                body={},
            ).execute()
            (
                self._service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=sheet_id,
                    range=f"{quoted_tab}!A1",
                    valueInputOption="RAW",
                    body={"values": values},
                )
                .execute()
            )
        except HttpError as exc:
            if exc.resp.status == 401:
                return ExportResult(success=False, error_class="AUTH")
            if exc.resp.status in (403, 404):
                return ExportResult(success=False, error_class="PERMANENT_EXTERNAL")
            if exc.resp.status == 400:
                return ExportResult(success=False, error_class="VALIDATION")
            if exc.resp.status == 429:
                return ExportResult(success=False, error_class="RATE_LIMIT")
            return ExportResult(success=False, error_class="TRANSIENT_NETWORK")
        except Exception:
            return ExportResult(success=False, error_class="TRANSIENT_NETWORK")
        # The header is intentionally excluded from the operational row count.
        return ExportResult(success=True, rows_written=len(rows))
