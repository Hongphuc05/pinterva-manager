from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.adapters.printerval.models import (
    AssetResult,
    DiscoverResult,
    OrderDetailResult,
    WriteResult,
)

# Real option text confirmed on the live site's job-type filter dropdown
# (docs/phase0-field-map.md: "Tất cả 2D&3D / 2D / 3D / ART / WOOD / CALENDAR /
# EMBROIDERY / AI"). V1 no longer hard-filters to 2D only (claude.md §16, changed
# 2026-09-07) — job type is a customer-facing label, not a processing constraint.
ALL_JOB_TYPES = "Tất cả 2D&3D"


@runtime_checkable
class PrintervalAdapter(Protocol):
    def discover_orders(
        self,
        status: str,
        job_type: str = ALL_JOB_TYPES,
        limit: int = 40,
        cursor: str | None = None,
    ) -> DiscoverResult: ...

    def get_order_detail(self, external_order_id: str) -> OrderDetailResult: ...

    def set_designer(self, external_order_id: str, designer_option: str) -> WriteResult: ...

    def set_status(self, external_order_id: str, target_status: str) -> WriteResult: ...

    def attach_result_link(self, external_order_id: str, drive_url: str) -> WriteResult: ...

    def download_asset(self, external_order_id: str) -> AssetResult: ...
