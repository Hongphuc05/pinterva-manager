from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.adapters.printerval.models import (
    AssetResult,
    DiscoverResult,
    OrderDetailResult,
    WriteResult,
)


@runtime_checkable
class PrintervalAdapter(Protocol):
    def discover_orders(
        self,
        status: str,
        job_type: str = "2D",
        limit: int = 40,
        cursor: str | None = None,
    ) -> DiscoverResult: ...

    def get_order_detail(self, external_order_id: str) -> OrderDetailResult: ...

    def set_designer(self, external_order_id: str, designer_option: str) -> WriteResult: ...

    def set_status(self, external_order_id: str, target_status: str) -> WriteResult: ...

    def attach_result_link(self, external_order_id: str, drive_url: str) -> WriteResult: ...

    def download_asset(self, external_order_id: str) -> AssetResult: ...
