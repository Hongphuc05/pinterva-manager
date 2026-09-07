from datetime import datetime, timezone

from app.adapters.google.fake_drive_adapter import FakeDriveAdapter
from app.adapters.google.fake_sheets_adapter import FakeSheetsAdapter


def test_export_snapshot_appends_rows():
    adapter = FakeSheetsAdapter()
    result = adapter.export_snapshot(
        rows=[{"order_id": "DJ0000001", "status": "Done"}],
        sheet_id="sheet-abc",
        exported_at=datetime.now(timezone.utc),
    )
    assert result.success is True
    assert result.rows_written == 1
    assert adapter.rows_by_sheet["sheet-abc"] == [{"order_id": "DJ0000001", "status": "Done"}]


def test_export_snapshot_accumulates_across_calls():
    adapter = FakeSheetsAdapter()
    adapter.export_snapshot(rows=[{"a": 1}], sheet_id="s1", exported_at=datetime.now(timezone.utc))
    adapter.export_snapshot(rows=[{"a": 2}], sheet_id="s1", exported_at=datetime.now(timezone.utc))
    assert len(adapter.rows_by_sheet["s1"]) == 2


def test_export_snapshot_handles_empty_rows():
    adapter = FakeSheetsAdapter()
    result = adapter.export_snapshot(rows=[], sheet_id="s1", exported_at=datetime.now(timezone.utc))
    assert result.success is True
    assert result.rows_written == 0


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
