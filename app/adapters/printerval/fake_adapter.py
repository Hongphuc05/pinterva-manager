from __future__ import annotations

from dataclasses import dataclass

from app.adapters.printerval.models import (
    AssetResult,
    DiscoverResult,
    OrderDetailResult,
    OrderSummary,
    WriteResult,
)


@dataclass
class _FakeOrder:
    external_order_id: str
    product_name: str
    designer: str | None
    status: str
    note_outsource: str = ""
    order_note: str = ""
    created_at: str = "2026-01-01T00:00:00"
    order_created_at: str = "2026-01-01T00:00:00"
    deadline_at: str = "2026-01-10T00:00:00"
    has_uploaded_design: bool = False
    drive_url: str | None = None


class FakePrintervalAdapter:
    """In-memory adapter for deterministic tests. Seed orders via `add_order`."""

    def __init__(self):
        self._orders: dict[str, _FakeOrder] = {}

    def add_order(self, **kwargs) -> _FakeOrder:
        order = _FakeOrder(**kwargs)
        self._orders[order.external_order_id] = order
        return order

    def discover_orders(
        self, status: str, job_type: str = "2D", limit: int = 40, cursor: str | None = None
    ) -> DiscoverResult:
        matched = [o for o in self._orders.values() if o.status == status]
        orders = [
            OrderSummary(
                external_order_id=o.external_order_id,
                product_name=o.product_name,
                designer=o.designer,
                status=o.status,
            )
            for o in matched[:limit]
        ]
        return DiscoverResult(success=True, orders=orders, cursor=None)

    def get_order_detail(self, external_order_id: str) -> OrderDetailResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return OrderDetailResult(success=False, error_class="VALIDATION")
        return OrderDetailResult(
            success=True,
            external_order_id=order.external_order_id,
            designer=order.designer,
            status=order.status,
            note_outsource=order.note_outsource,
            order_note=order.order_note,
            created_at=order.created_at,
            order_created_at=order.order_created_at,
            deadline_at=order.deadline_at,
            has_uploaded_design=order.has_uploaded_design,
        )

    def set_designer(self, external_order_id: str, designer_option: str) -> WriteResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return WriteResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        order.designer = designer_option
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"designer": order.designer},
        )

    def set_status(self, external_order_id: str, target_status: str) -> WriteResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return WriteResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        order.status = target_status
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"status": order.status},
        )

    def attach_result_link(self, external_order_id: str, drive_url: str) -> WriteResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return WriteResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        order.drive_url = drive_url
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"drive_url": order.drive_url},
        )

    def download_asset(self, external_order_id: str) -> AssetResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return AssetResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        return AssetResult(
            success=True,
            external_order_id=external_order_id,
            local_path=f"/tmp/fake-assets/{external_order_id}.png",
            checksum="fakechecksum",
        )
