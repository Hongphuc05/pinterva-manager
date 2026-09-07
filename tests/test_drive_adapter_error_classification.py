"""Pure error-classification unit tests for GoogleDriveAdapter.verify_url.

No real Google API/credentials involved (unlike test_google_real_adapters.py) — this
just proves HttpError status codes and non-HttpError exceptions map to the right
ErrorClass, per claude.md §11 (only retryable classes get retried), and that the
existing 404/403 "successful check" branches (not error paths) are unchanged.
"""

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.adapters.google.drive_adapter import GoogleDriveAdapter

_VALID_URL = "https://drive.google.com/file/d/abc123/view"


def _adapter_raising(exc: Exception) -> GoogleDriveAdapter:
    """Build a GoogleDriveAdapter without touching real credentials/network,
    whose files().get().execute() raises the given exception."""
    adapter = GoogleDriveAdapter.__new__(GoogleDriveAdapter)

    class _FakeGet:
        def execute(self):
            raise exc

    class _FakeFiles:
        def get(self, **kwargs):
            return _FakeGet()

    class _FakeService:
        def files(self):
            return _FakeFiles()

    adapter._service = _FakeService()
    return adapter


@pytest.mark.parametrize(
    ("status", "expected_success", "expected_error_class"),
    [
        (404, True, None),  # unchanged: successful check, file does not exist
        (403, True, None),  # unchanged: successful check, file exists but inaccessible
        (401, False, "AUTH"),
        (400, False, "VALIDATION"),
        (500, False, "TRANSIENT_NETWORK"),
    ],
)
def test_verify_url_classifies_http_errors(status, expected_success, expected_error_class):
    adapter = _adapter_raising(HttpError(httplib2.Response({"status": status}), b"{}"))
    result = adapter.verify_url(_VALID_URL)
    assert result.success is expected_success
    assert result.error_class == expected_error_class


def test_verify_url_404_reports_not_exists_not_accessible():
    adapter = _adapter_raising(HttpError(httplib2.Response({"status": 404}), b"{}"))
    result = adapter.verify_url(_VALID_URL)
    assert result.exists is False
    assert result.accessible is False


def test_verify_url_403_reports_exists_but_not_accessible():
    adapter = _adapter_raising(HttpError(httplib2.Response({"status": 403}), b"{}"))
    result = adapter.verify_url(_VALID_URL)
    assert result.exists is True
    assert result.accessible is False


def test_verify_url_non_http_error_returns_typed_transient_result():
    # A TimeoutError, SSL error, or google.auth's RefreshError must not escape raised —
    # it has to come back as a typed, non-retryable-by-default TRANSIENT_NETWORK result.
    adapter = _adapter_raising(TimeoutError("connection timed out"))
    result = adapter.verify_url(_VALID_URL)
    assert result.success is False
    assert result.error_class == "TRANSIENT_NETWORK"
