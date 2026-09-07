"""Pure error-classification unit tests for GoogleSheetsAdapter.export_snapshot.

No real Google API/credentials involved (unlike test_google_real_adapters.py) — this
just proves HttpError status codes map to the right ErrorClass, per claude.md §11
(only retryable classes get retried).
"""

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.adapters.google.sheets_adapter import GoogleSheetsAdapter


def _adapter_with_fake_append(status: int) -> GoogleSheetsAdapter:
    """Build a GoogleSheetsAdapter without touching real credentials/network,
    whose values().append().execute() raises an HttpError with the given status."""
    adapter = GoogleSheetsAdapter.__new__(GoogleSheetsAdapter)

    class _FakeAppend:
        def execute(self):
            raise HttpError(httplib2.Response({"status": status}), b"{}")

    class _FakeValues:
        def append(self, **kwargs):
            return _FakeAppend()

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
        (403, "PERMANENT_EXTERNAL"),
        (404, "PERMANENT_EXTERNAL"),
        (400, "VALIDATION"),
        (500, "TRANSIENT_NETWORK"),
    ],
)
def test_export_snapshot_classifies_http_errors(status, expected_error_class):
    from datetime import UTC, datetime

    adapter = _adapter_with_fake_append(status)
    result = adapter.export_snapshot(
        rows=[{"order_id": "DJ0000001"}], sheet_id="whatever", exported_at=datetime.now(UTC)
    )
    assert result.success is False
    assert result.error_class == expected_error_class
