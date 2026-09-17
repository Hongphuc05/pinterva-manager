from datetime import UTC, datetime

from app.adapters.google.fake_drive_adapter import FakeDriveAdapter
from app.adapters.google.fake_sheets_adapter import FakeSheetsAdapter

SHEET_ID = "sheet-abc"
TAB_NAME = "Order Backup"


def test_export_snapshot_replaces_rows():
    adapter = FakeSheetsAdapter()
    result = adapter.export_snapshot(
        rows=[{"Mã đơn": "DJ0000001", "Link DES nộp bài": "https://drive/one"}],
        sheet_id=SHEET_ID,
        tab_name=TAB_NAME,
        exported_at=datetime.now(UTC),
    )
    assert result.success is True
    assert result.rows_written == 1
    assert adapter.rows_by_sheet[(SHEET_ID, TAB_NAME)] == [
        {"Mã đơn": "DJ0000001", "Link DES nộp bài": "https://drive/one"}
    ]


def test_export_snapshot_is_idempotent_for_same_sheet_and_tab():
    adapter = FakeSheetsAdapter()
    adapter.export_snapshot(
        rows=[{"Mã đơn": "DJ0000001", "Link DES nộp bài": "https://drive/old"}],
        sheet_id="s1",
        tab_name=TAB_NAME,
        exported_at=datetime.now(UTC),
    )
    adapter.export_snapshot(
        rows=[{"Mã đơn": "DJ0000002", "Link DES nộp bài": "https://drive/new"}],
        sheet_id="s1",
        tab_name=TAB_NAME,
        exported_at=datetime.now(UTC),
    )
    assert adapter.rows_by_sheet[("s1", TAB_NAME)] == [
        {"Mã đơn": "DJ0000002", "Link DES nộp bài": "https://drive/new"}
    ]


def test_export_snapshot_handles_empty_rows_by_replacing_with_header_only_snapshot():
    adapter = FakeSheetsAdapter()
    adapter.export_snapshot(
        rows=[{"Mã đơn": "DJ0000001", "Link DES nộp bài": "https://drive/one"}],
        sheet_id="s1",
        tab_name=TAB_NAME,
        exported_at=datetime.now(UTC),
    )
    result = adapter.export_snapshot(
        rows=[], sheet_id="s1", tab_name=TAB_NAME, exported_at=datetime.now(UTC)
    )
    assert result.success is True
    assert result.rows_written == 0
    assert adapter.rows_by_sheet[("s1", TAB_NAME)] == []


def test_verify_url_recognizes_known_file():
    adapter = FakeDriveAdapter(known_file_ids={"abc123"})
    result = adapter.verify_url("https://drive.google.com/file/d/abc123/view")
    assert result.success is True
    assert result.exists is True
    assert result.accessible is True


def test_verify_url_flags_missing_file():
    adapter = FakeDriveAdapter(known_file_ids={"abc123"})
    result = adapter.verify_url("https://drive.google.com/file/d/notreal/view")
    assert result.success is True
    assert result.exists is False


def test_verify_url_rejects_malformed_url():
    adapter = FakeDriveAdapter(known_file_ids=set())
    result = adapter.verify_url("not-a-drive-url")
    assert result.success is False
    assert result.error_class == "VALIDATION"


def test_verify_url_recognizes_legacy_id_query_param_url():
    adapter = FakeDriveAdapter(known_file_ids={"abc123"})
    result = adapter.verify_url("https://drive.google.com/open?id=abc123")
    assert result.success is True
    assert result.exists is True
    assert result.accessible is True
