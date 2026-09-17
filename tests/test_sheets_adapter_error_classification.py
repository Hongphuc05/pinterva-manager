"""Pure tests for GoogleSheetsAdapter snapshot-write error handling."""

from datetime import UTC, datetime

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.adapters.google.sheets_adapter import GoogleSheetsAdapter


def _adapter_with_fake_request_failure(status: int) -> GoogleSheetsAdapter:
    adapter = GoogleSheetsAdapter.__new__(GoogleSheetsAdapter)

    class _FailingRequest:
        def execute(self):
            raise HttpError(httplib2.Response({"status": status}), b"{}")

    class _FakeValues:
        def clear(self, **kwargs):
            return _FailingRequest()

        def update(self, **kwargs):
            return _FailingRequest()

    class _FakeSpreadsheets:
        def values(self):
            return _FakeValues()

    class _FakeService:
        def spreadsheets(self):
            return _FakeSpreadsheets()

    adapter._service = _FakeService()
    return adapter


@pytest.mark.parametrize(
    ("status", "expected_error_class"),
    [
        (401, "AUTH"),
        (403, "PERMANENT_EXTERNAL"),
        (404, "PERMANENT_EXTERNAL"),
        (400, "VALIDATION"),
        (429, "RATE_LIMIT"),
        (500, "TRANSIENT_NETWORK"),
    ],
)
def test_export_snapshot_classifies_http_errors(status, expected_error_class):
    adapter = _adapter_with_fake_request_failure(status)
    result = adapter.export_snapshot(
        rows=[{"Mã đơn": "DJ0000001", "Link DES nộp bài": ""}],
        sheet_id="whatever",
        tab_name="Order Backup",
        exported_at=datetime.now(UTC),
    )
    assert result.success is False
    assert result.error_class == expected_error_class


def test_export_snapshot_clears_then_writes_exactly_two_columns():
    adapter = GoogleSheetsAdapter.__new__(GoogleSheetsAdapter)
    calls: list[tuple[str, dict]] = []

    class _Request:
        def execute(self):
            return {}

    class _FakeValues:
        def clear(self, **kwargs):
            calls.append(("clear", kwargs))
            return _Request()

        def update(self, **kwargs):
            calls.append(("update", kwargs))
            return _Request()

    class _FakeSpreadsheets:
        def values(self):
            return _FakeValues()

    class _FakeService:
        def spreadsheets(self):
            return _FakeSpreadsheets()

    adapter._service = _FakeService()
    result = adapter.export_snapshot(
        rows=[{"Mã đơn": "DJ0000001", "Link DES nộp bài": "https://drive/result"}],
        sheet_id="sheet-id",
        tab_name="Đơn của Phúc",
        exported_at=datetime.now(UTC),
    )

    assert result.rows_written == 1
    assert calls[0] == (
        "clear",
        {"spreadsheetId": "sheet-id", "range": "'Đơn của Phúc'!A:Z", "body": {}},
    )
    assert calls[1] == (
        "update",
        {
            "spreadsheetId": "sheet-id",
            "range": "'Đơn của Phúc'!A1",
            "valueInputOption": "RAW",
            "body": {
                "values": [
                    ["Mã đơn", "Link DES nộp bài"],
                    ["DJ0000001", "https://drive/result"],
                ]
            },
        },
    )
