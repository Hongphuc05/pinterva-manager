from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.db.models import Assignment, Operation, Order, ResultVersion, User
from app.adapters.errors import ErrorClass
from app.adapters.google.fake_sheets_adapter import FakeSheetsAdapter
from app.adapters.google.models import ExportResult
from app.application.order_sheet_backup import (
    OrderSheetConfigurationError,
    OrderSheetExportError,
    build_order_sheet_rows,
    export_order_sheet_snapshot,
    parse_google_spreadsheet_id,
)

SHEET_URL = "https://docs.google.com/spreadsheets/d/sheet_ABC-123/edit#gid=0"
EXPORTED_AT = datetime(2026, 9, 18, 0, 10, tzinfo=UTC)


def _result_data(db_session):
    designer = User(
        username="sheet-designer",
        full_name="Sheet Designer",
        role="designer",
        password_hash="not-used-by-test",
    )
    first = Order(external_order_id="DJ0000002", state="WAITING")
    second = Order(external_order_id="DJ0000001", state="WAITING")
    missing_result = Order(external_order_id="DJ0000003", state="WAITING")
    db_session.add_all([designer, first, second, missing_result])
    db_session.flush()

    first_assignment = Assignment(order_id=first.id, designer_id=designer.id, status="approved")
    second_assignment = Assignment(order_id=second.id, designer_id=designer.id, status="approved")
    db_session.add_all([first_assignment, second_assignment])
    db_session.flush()

    db_session.add_all(
        [
            ResultVersion(
                assignment_id=first_assignment.id,
                drive_url="https://drive/older",
                version_marker=1,
                submitted_at=EXPORTED_AT - timedelta(days=2),
            ),
            ResultVersion(
                assignment_id=first_assignment.id,
                drive_url="https://drive/latest",
                version_marker=2,
                submitted_at=EXPORTED_AT - timedelta(days=1),
            ),
            ResultVersion(
                assignment_id=second_assignment.id,
                drive_url="https://drive/no-submission-time",
                version_marker=1,
                submitted_at=None,
            ),
        ]
    )
    db_session.commit()


def test_parse_google_spreadsheet_id_accepts_a_standard_edit_url():
    assert parse_google_spreadsheet_id(SHEET_URL) == "sheet_ABC-123"


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.google.com/spreadsheets/d/sheet-id/edit",
        "https://example.com/spreadsheets/d/sheet-id/edit",
        "https://docs.google.com/document/d/not-a-sheet/edit",
        "https://docs.google.com/spreadsheets/d/has space/edit",
    ],
)
def test_parse_google_spreadsheet_id_rejects_non_sheet_urls(url):
    with pytest.raises(OrderSheetConfigurationError):
        parse_google_spreadsheet_id(url)


def test_build_order_sheet_rows_uses_latest_submission_and_keeps_empty_links(db_session):
    _result_data(db_session)

    assert build_order_sheet_rows(db_session) == [
        {"Mã đơn": "DJ0000001", "Link DES nộp bài": "https://drive/no-submission-time"},
        {"Mã đơn": "DJ0000002", "Link DES nộp bài": "https://drive/latest"},
        {"Mã đơn": "DJ0000003", "Link DES nộp bài": ""},
    ]


def test_export_snapshot_is_idempotent_and_writes_an_operation_audit(db_session):
    _result_data(db_session)
    adapter = FakeSheetsAdapter()

    first = export_order_sheet_snapshot(
        db_session,
        lambda: adapter,
        sheet_url=SHEET_URL,
        tab_name="Order Backup",
        timezone_name="Asia/Ho_Chi_Minh",
        exported_at=EXPORTED_AT,
    )
    second = export_order_sheet_snapshot(
        db_session,
        lambda: adapter,
        sheet_url=SHEET_URL,
        tab_name="Order Backup",
        timezone_name="Asia/Ho_Chi_Minh",
        exported_at=EXPORTED_AT,
    )

    assert first == second
    assert first["rows_written"] == 3
    assert adapter.export_calls == 1
    operation = db_session.query(Operation).filter_by(command_name="order_sheet_backup").one()
    assert operation.status == "completed"
    assert operation.result == first


def test_export_snapshot_marks_transient_error_for_retry_without_storing_provider_text(db_session):
    class _TransientAdapter:
        def export_snapshot(self, rows, sheet_id, tab_name, exported_at):
            return ExportResult(success=False, error_class=ErrorClass.TRANSIENT_NETWORK)

    with pytest.raises(OrderSheetExportError) as raised:
        export_order_sheet_snapshot(
            db_session,
            _TransientAdapter,
            sheet_url=SHEET_URL,
            tab_name="Order Backup",
            timezone_name="Asia/Ho_Chi_Minh",
            exported_at=EXPORTED_AT,
        )

    assert raised.value.retryable is True
    operation = db_session.query(Operation).filter_by(command_name="order_sheet_backup").one()
    assert operation.status == "failed"
    assert operation.evidence == {
        "target": "google_sheets",
        "error_class": "TRANSIENT_NETWORK",
    }


def test_export_snapshot_audits_invalid_credential_factory_as_permanent_failure(db_session):
    def missing_credential():
        raise FileNotFoundError("do not persist this filesystem detail")

    with pytest.raises(OrderSheetExportError) as raised:
        export_order_sheet_snapshot(
            db_session,
            missing_credential,
            sheet_url=SHEET_URL,
            tab_name="Order Backup",
            timezone_name="Asia/Ho_Chi_Minh",
            exported_at=EXPORTED_AT,
        )

    assert raised.value.error_class == ErrorClass.PERMANENT_EXTERNAL
    operation = db_session.query(Operation).filter_by(command_name="order_sheet_backup").one()
    assert operation.status == "failed"
    assert operation.evidence == {
        "target": "google_sheets",
        "error_class": "PERMANENT_EXTERNAL",
    }
