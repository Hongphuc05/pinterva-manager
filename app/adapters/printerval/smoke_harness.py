from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.adapters.printerval.interface import PrintervalAdapter
from app.adapters.printerval.models import WriteResult


@dataclass
class OrderSnapshot:
    external_order_id: str
    designer: str | None
    status: str | None
    note_outsource: str | None = None


def snapshot_order(adapter: PrintervalAdapter, external_order_id: str) -> OrderSnapshot:
    detail = adapter.get_order_detail(external_order_id)
    if not detail.success:
        raise RuntimeError(f"Cannot snapshot {external_order_id}: {detail.error_class}")
    return OrderSnapshot(
        external_order_id=external_order_id,
        designer=detail.designer,
        status=detail.status,
        note_outsource=detail.note_outsource,
    )


def restore_order(adapter: PrintervalAdapter, snapshot: OrderSnapshot) -> None:
    errors: list[str] = []
    if snapshot.designer is not None:
        result = adapter.set_designer(snapshot.external_order_id, snapshot.designer)
        if not result.success:
            errors.append(f"restore designer failed: {result.error_class}")
    if snapshot.status is not None:
        result = adapter.set_status(snapshot.external_order_id, snapshot.status)
        if not result.success:
            errors.append(f"restore status failed: {result.error_class}")
    if snapshot.note_outsource is not None:
        result = adapter.attach_result_link(snapshot.external_order_id, snapshot.note_outsource)
        if not result.success:
            errors.append(f"restore note_outsource failed: {result.error_class}")

    verify = snapshot_order(adapter, snapshot.external_order_id)
    if (
        verify.designer != snapshot.designer
        or verify.status != snapshot.status
        or verify.note_outsource != snapshot.note_outsource
    ):
        errors.append(
            f"restore verification mismatch: expected designer={snapshot.designer!r} "
            f"status={snapshot.status!r} note_outsource={snapshot.note_outsource!r}, "
            f"got designer={verify.designer!r} status={verify.status!r} "
            f"note_outsource={verify.note_outsource!r}"
        )
    if errors:
        raise RuntimeError(
            f"RESTORE FAILED for {snapshot.external_order_id}: {'; '.join(errors)}. "
            "Manual intervention required — the order may be left in a modified state."
        )


def run_write_method_smoke_test(
    adapter: PrintervalAdapter,
    external_order_id: str,
    action: Callable[[PrintervalAdapter, str], WriteResult],
) -> None:
    """Run snapshot -> act -> verify -> restore -> verify-restore for one write method.

    `action(adapter, external_order_id)` performs the write under test and
    must return a WriteResult. Restore always runs, even if `action` raises.
    """
    snapshot = snapshot_order(adapter, external_order_id)
    try:
        result = action(adapter, external_order_id)
        if not result.success:
            raise RuntimeError(f"Action failed: {result.error_class}")
    finally:
        restore_order(adapter, snapshot)
