"""PrintervalApiAdapter implements PrintervalAdapter using PrintervalApiClient
for API-first discovery of Waiting orders.

It delegates write operations and detail/asset extraction to an optional fallback
adapter (e.g. PrintervalPlaywrightAdapter) until HTTP endpoints for those operations
have been verified.
"""

from __future__ import annotations

from app.adapters.errors import ErrorClass
from app.adapters.printerval.api_client import (
    PrintervalApiClient,
    PrintervalApiConfigurationError,
    PrintervalApiError,
)
from app.adapters.printerval.image_helper import (
    download_and_save_image,
    extract_image_url_from_dict_or_html,
)
from app.adapters.printerval.interface import ALL_JOB_TYPES, PrintervalAdapter
from app.adapters.printerval.models import (
    AssetResult,
    DiscoverResult,
    OrderDetailResult,
    OrderSummary,
    WriteResult,
)


class PrintervalApiAdapter:
    """An API-first adapter that uses server-side HTTP requests for discovering
    Waiting orders, delegating write/detail operations to an optional fallback
    adapter (e.g. Playwright).
    """

    def __init__(
        self,
        api_client: PrintervalApiClient,
        fallback_adapter: PrintervalAdapter | None = None,
    ) -> None:
        self.api_client = api_client
        self.fallback_adapter = fallback_adapter

    def discover_orders(
        self,
        status: str,
        job_type: str = ALL_JOB_TYPES,
        limit: int = 40,
        cursor: str | None = None,
        platform_id: str | None = None,
    ) -> DiscoverResult:
        if job_type != ALL_JOB_TYPES:
            # Only "all" is a confirmed-safe value for the fast HTTP find endpoint
            # (docs/phase0-field-map.md §4) — every other job_type label is only
            # verified against the live DOM's <select>, via the Playwright fallback's
            # own discover_orders. Guessing an HTTP query value for it risks the exact
            # incident already on record: a mismatched filter string silently returning
            # 0 orders instead of erroring.
            if self.fallback_adapter:
                return self.fallback_adapter.discover_orders(
                    status=status, job_type=job_type, limit=limit, cursor=cursor, platform_id=platform_id
                )
            return DiscoverResult(
                success=False,
                error_class=ErrorClass.PERMANENT_EXTERNAL.value,
                evidence={"message": f"job_type={job_type!r} requires the Playwright fallback, none configured"},
            )

        page_id = int(cursor) if cursor and cursor.isdigit() else 0
        try:
            page = self.api_client.discover_waiting_page(page_size=limit, page_id=page_id)
        except Exception as exc:
            error_cls = (
                exc.error_class.value
                if isinstance(exc, PrintervalApiError)
                else ErrorClass.PERMANENT_EXTERNAL.value
            )
            if isinstance(exc, PrintervalApiError) and exc.error_class == ErrorClass.AUTH:
                return DiscoverResult(
                    success=False,
                    error_class=error_cls,
                    evidence={"message": str(exc)},
                )
            if self.fallback_adapter:
                return self.fallback_adapter.discover_orders(
                    status=status, job_type=job_type, limit=limit, cursor=cursor, platform_id=platform_id
                )
            return DiscoverResult(
                success=False,
                error_class=error_cls,
                evidence={"message": str(exc)},
            )

        discovered: list[OrderSummary] = []
        for row in page.orders:
            order_id = str(
                row.get("code")
                or row.get("job_code")
                or row.get("external_order_id")
                or row.get("id")
                or ""
            ).strip()
            if order_id:
                product_info = row.get("product") if isinstance(row.get("product"), dict) else {}
                product_name = str(
                    product_info.get("name")
                    or row.get("product_name")
                    or row.get("name")
                    or row.get("job_title")
                    or row.get("title")
                    or "Đơn 2D Custom"
                )
                sku = str(product_info.get("sku") or row.get("sku") or "")
                category = str(product_info.get("category_name") or row.get("product_category") or "")

                raw_image_url = extract_image_url_from_dict_or_html(row)
                local_path = (
                    download_and_save_image(order_id, raw_image_url, platform_id=platform_id)
                    if raw_image_url
                    else None
                )
                final_thumbnail = local_path or raw_image_url

                template_jobs = row.get("templateJobs")
                if not isinstance(template_jobs, list):
                    template_jobs = None

                discovered.append(
                    OrderSummary(
                        external_order_id=order_id,
                        product_name=product_name,
                        thumbnail_url=final_thumbnail,
                        status=status,
                        template_jobs=template_jobs,
                        sku=sku or None,
                        product_category=category or None,
                    )
                )

        next_cursor = str(page_id + 1) if len(page.orders) >= limit else None
        return DiscoverResult(
            success=True,
            orders=discovered,
            cursor=next_cursor,
            total_found=len(discovered),
        )

    def get_order_detail(
        self, external_order_id: str, platform_id: str | None = None
    ) -> OrderDetailResult:
        if self.fallback_adapter:
            return self.fallback_adapter.get_order_detail(external_order_id, platform_id=platform_id)
        return OrderDetailResult(
            success=False,
            error_class=ErrorClass.PERMANENT_EXTERNAL.value,
            evidence={"message": "No fallback adapter provided for get_order_detail"},
        )

    def set_designer(self, external_order_id: str, designer_option: str) -> WriteResult:
        if self.fallback_adapter:
            return self.fallback_adapter.set_designer(external_order_id, designer_option)
        return WriteResult(
            success=False,
            error_class=ErrorClass.PERMANENT_EXTERNAL.value,
            evidence={"message": "No fallback adapter provided for set_designer"},
        )

    def set_status(self, external_order_id: str, target_status: str) -> WriteResult:
        if self.fallback_adapter:
            return self.fallback_adapter.set_status(external_order_id, target_status)
        return WriteResult(
            success=False,
            error_class=ErrorClass.PERMANENT_EXTERNAL.value,
            evidence={"message": "No fallback adapter provided for set_status"},
        )

    def attach_result_link(self, external_order_id: str, drive_url: str) -> WriteResult:
        if self.fallback_adapter:
            return self.fallback_adapter.attach_result_link(external_order_id, drive_url)
        return WriteResult(
            success=False,
            error_class=ErrorClass.PERMANENT_EXTERNAL.value,
            evidence={"message": "No fallback adapter provided for attach_result_link"},
        )

    def download_asset(
        self, external_order_id: str, platform_id: str | None = None
    ) -> AssetResult:
        if self.fallback_adapter:
            return self.fallback_adapter.download_asset(external_order_id, platform_id=platform_id)
        return AssetResult(
            success=False,
            error_class=ErrorClass.PERMANENT_EXTERNAL.value,
            evidence={"message": "No fallback adapter provided for download_asset"},
        )
