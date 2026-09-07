import os
from datetime import UTC, datetime

import pytest

CREDENTIALS_PATH = "credentials/google-service-account.json"

# Fixed, pre-existing spreadsheet living inside a Drive folder shared Editor with the
# service account. The service account has zero Drive storage quota and no Shared Drive
# access, so it cannot create (or delete) files itself — see task-8-report.md for the
# verified evidence. A human created this one spreadsheet by hand for exactly this test
# to read/write against; it is never created or deleted here, only cleared before and
# after use.
# Not a secret, but a real personal-Drive resource pointer — kept in source (rather than
# created per-run) only because the service account cannot create its own throwaway
# sheets; see task-8-report.md.
FIXTURE_SHEET_ID = "1sYAXViNT8QwuHZHEvN013PUr4ex5ASsx4PEuzsCGBoA"
_CLEAR_RANGE = "A1:Z100"

pytestmark = pytest.mark.skipif(
    not os.path.exists(CREDENTIALS_PATH),
    reason="No Google service account credential present (expected on CI)",
)


@pytest.fixture()
def fixture_sheet():
    # Reads/writes ONE fixed shared sheet rather than an isolated one per run (same
    # zero-quota root cause) — concurrent runs against this credential could race.
    # Acceptable for a local-only, credential-gated test never run in CI.
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    sheets_service = build("sheets", "v4", credentials=credentials)

    def clear():
        sheets_service.spreadsheets().values().clear(
            spreadsheetId=FIXTURE_SHEET_ID, range=_CLEAR_RANGE, body={}
        ).execute()

    clear()
    yield FIXTURE_SHEET_ID
    clear()


def test_export_snapshot_writes_rows_to_real_sheet(fixture_sheet):
    from app.adapters.google.sheets_adapter import GoogleSheetsAdapter

    adapter = GoogleSheetsAdapter(credentials_path=CREDENTIALS_PATH)
    result = adapter.export_snapshot(
        rows=[{"order_id": "DJ0000001", "status": "Done"}],
        sheet_id=fixture_sheet,
        exported_at=datetime.now(UTC),
    )
    assert result.success is True
    assert result.rows_written == 1


def test_verify_url_detects_missing_file():
    from app.adapters.google.drive_adapter import GoogleDriveAdapter

    adapter = GoogleDriveAdapter(credentials_path=CREDENTIALS_PATH)
    result = adapter.verify_url("https://drive.google.com/file/d/nonexistent000000/view")
    assert result.success is True
    assert result.exists is False
