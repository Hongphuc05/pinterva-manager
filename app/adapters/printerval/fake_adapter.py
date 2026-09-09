from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.adapters.printerval.interface import ALL_JOB_TYPES
from app.adapters.printerval.models import (
    AssetResult,
    CustomConfig,
    DesignerOptionsResult,
    DiscoverResult,
    OrderDetailResult,
    OrderSummary,
    ProductVariant,
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
    created_at: datetime | None = None
    order_created_at: datetime | None = None
    deadline_at: datetime | None = None
    has_uploaded_design: bool = False
    thumbnail_url: str | None = None
    sku: str | None = None
    product_category: str | None = None
    product_variants: list[ProductVariant] = field(default_factory=list)
    has_template: bool = False
    multiple_design: bool = False
    double_sided: bool = False
    priority_label: str | None = None
    custom_config: CustomConfig | None = None
    design_tool_url: str | None = None
    template_jobs: list[dict] | None = None
    checksum: str = "fakechecksum"


class FakePrintervalAdapter:
    """In-memory adapter for deterministic tests. Seed orders via `add_order`."""

    def __init__(self):
        self._orders: dict[str, _FakeOrder] = {}

    def list_designer_options(self, external_order_id: str) -> DesignerOptionsResult:
        if external_order_id not in self._orders:
            return DesignerOptionsResult(success=False, error_class="VALIDATION")
        options = sorted(
            {order.designer for order in self._orders.values() if order.designer}
            | {"Nguyễn Thị Thuý Hường - 2D Prin"}
        )
        return DesignerOptionsResult(success=True, options=options)

    def add_order(self, **kwargs) -> _FakeOrder:
        order = _FakeOrder(**kwargs)
        self._orders[order.external_order_id] = order
        return order

    def discover_orders(
        self,
        status: str,
        job_type: str = ALL_JOB_TYPES,
        limit: int = 40,
        cursor: str | None = None,
        platform_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
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

    def get_order_detail(
        self, external_order_id: str, platform_id: str | None = None
    ) -> OrderDetailResult:
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
            product_name=order.product_name,
            thumbnail_url=order.thumbnail_url,
            sku=order.sku,
            product_category=order.product_category,
            product_variants=order.product_variants,
            has_template=order.has_template,
            multiple_design=order.multiple_design,
            double_sided=order.double_sided,
            priority_label=order.priority_label,
            custom_config=order.custom_config,
            design_tool_url=order.design_tool_url,
            template_jobs=order.template_jobs,
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
        order.note_outsource = drive_url
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"result_link": order.note_outsource},
        )

    def download_asset(
        self, external_order_id: str, platform_id: str | None = None
    ) -> AssetResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return AssetResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        return AssetResult(
            success=True,
            external_order_id=external_order_id,
            local_path=f"/tmp/fake-assets/{external_order_id}.png",
            checksum=order.checksum,
        )
