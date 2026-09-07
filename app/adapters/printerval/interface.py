from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.adapters.printerval.models import (
    AssetResult,
    DiscoverResult,
    OrderDetailResult,
    WriteResult,
)

# Real option text, confirmed live against the actual admin page DOM 2026-09-07
# (Phase 0's field-map.md transcribed it as "Tất cả 2D&3D" without spaces around "&" —
# that was wrong; the live dropdown genuinely renders "Tất cả 2D & 3D" with spaces on
# both sides, confirmed by screenshot. _find_select_by_option_text does an exact
# .strip() == match, so this spacing must be byte-exact or the whole filter silently
# fails closed — see the incident this fixed: a real "Waiting" order sat visible on
# the live site while the crawl reported zero, because the mismatched string raised
# LookupError -> EXTERNAL_CHANGED, dead-lettered, and returned as "no new orders"
# instead of surfacing as an error). V1 no longer hard-filters to 2D only (claude.md
# §16, changed 2026-09-07) — job type is a customer-facing label, not a processing
# constraint.
ALL_JOB_TYPES = "Tất cả 2D & 3D"


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
