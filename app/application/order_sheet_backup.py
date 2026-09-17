from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.adapters.db.models import Assignment, Operation, Order, ResultVersion
from app.adapters.errors import ErrorClass
from app.adapters.google.sheets_interface import SheetsAdapter
from app.application.operations import run_idempotent

_ORDER_ID_COLUMN = "Mã đơn"
_RESULT_URL_COLUMN = "Link DES nộp bài"


class OrderSheetConfigurationError(ValueError):
    """The configured Google Sheet URL is not a supported spreadsheet URL."""


class OrderSheetExportError(RuntimeError):
    def __init__(self, error_class: ErrorClass):
        self.error_class = error_class
        super().__init__(f"Google Sheets export failed with {error_class.value}")

    @property
    def retryable(self) -> bool:
        return self.error_class in {
            ErrorClass.TRANSIENT_NETWORK,
            ErrorClass.RATE_LIMIT,
            ErrorClass.UNKNOWN_OUTCOME,
        }


def parse_google_spreadsheet_id(sheet_url: str) -> str:
    """Extract a spreadsheet id only from an HTTPS docs.google.com URL."""
    parsed = urlparse(sheet_url.strip())
    if parsed.scheme != "https" or parsed.netloc not in {"docs.google.com", "www.docs.google.com"}:
        raise OrderSheetConfigurationError(
            "GOOGLE_SHEETS_ORDER_BACKUP_URL must be a docs.google.com HTTPS URL"
        )

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 3 or path_parts[0:2] != ["spreadsheets", "d"]:
        raise OrderSheetConfigurationError(
            "Google Sheets URL must contain /spreadsheets/d/<spreadsheet-id>"
        )

    spreadsheet_id = path_parts[2]
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if not spreadsheet_id or any(char not in allowed for char in spreadsheet_id):
        raise OrderSheetConfigurationError("Google Sheets spreadsheet id is invalid")
    return spreadsheet_id


def build_order_sheet_rows(session: Session) -> list[dict[str, str]]:
    """Return one deterministic row for every stored external order.

    A result may be resubmitted or belong to a replacement assignment. Ordering the
    joined rows first by latest submission, then creation time, lets the first row for
    each order be its current submitted link while retaining orders with no result.
    """
    records = (
        session.query(
            Order.id,
            Order.external_order_id,
            ResultVersion.drive_url,
        )
        .outerjoin(Assignment, Assignment.order_id == Order.id)
        .outerjoin(ResultVersion, ResultVersion.assignment_id == Assignment.id)
        .filter(Order.external_order_id.is_not(None))
        .order_by(
            Order.external_order_id.asc(),
            ResultVersion.submitted_at.desc().nulls_last(),
            ResultVersion.created_at.desc(),
        )
        .all()
    )

    rows: list[dict[str, str]] = []
    selected_order_ids = set()
    for order_id, external_order_id, drive_url in records:
        if order_id in selected_order_ids:
            continue
        selected_order_ids.add(order_id)
        rows.append(
            {
                _ORDER_ID_COLUMN: external_order_id,
                _RESULT_URL_COLUMN: drive_url or "",
            }
        )
    return rows


def _operation_key(
    *, exported_at: datetime, sheet_id: str, tab_name: str, timezone_name: str
) -> tuple[str, str]:
    export_date = exported_at.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    fingerprint = hashlib.sha256(f"{sheet_id}:{tab_name}:v1".encode()).hexdigest()
    return f"order_sheet_backup:{export_date}:{fingerprint[:16]}", fingerprint


def export_order_sheet_snapshot(
    session: Session,
    adapter_factory: Callable[[], SheetsAdapter],
    *,
    sheet_url: str,
    tab_name: str,
    timezone_name: str,
    exported_at: datetime | None = None,
) -> dict:
    """Write the daily reporting snapshot and retain its audit/idempotency record."""
    if not tab_name.strip():
        raise OrderSheetConfigurationError("GOOGLE_SHEETS_ORDER_BACKUP_TAB must not be empty")

    now = exported_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    sheet_id = parse_google_spreadsheet_id(sheet_url)
    idempotency_key, fingerprint = _operation_key(
        exported_at=now,
        sheet_id=sheet_id,
        tab_name=tab_name,
        timezone_name=timezone_name,
    )

    def _export() -> dict:
        rows = build_order_sheet_rows(session)
        # Create the authenticated client only after the operation row has been
        # committed. A credential/network failure is therefore visible in the audit
        # record and can be retried safely.
        try:
            adapter = adapter_factory()
        except (OSError, ValueError) as exc:
            raise OrderSheetExportError(ErrorClass.PERMANENT_EXTERNAL) from exc
        result = adapter.export_snapshot(rows, sheet_id, tab_name, now)
        if not result.success:
            raise OrderSheetExportError(result.error_class or ErrorClass.TRANSIENT_NETWORK)
        return {
            "rows_written": result.rows_written,
            "exported_at": now.isoformat(),
            "target": "google_sheets",
        }

    try:
        return run_idempotent(
            session,
            idempotency_key,
            "order_sheet_backup",
            _export,
            request_fingerprint=fingerprint,
        )
    except OrderSheetExportError as exc:
        # Never persist provider response text: it may contain URLs or credentials.
        operation = session.query(Operation).filter_by(idempotency_key=idempotency_key).one()
        operation.evidence = {"target": "google_sheets", "error_class": exc.error_class.value}
        session.commit()
        raise
