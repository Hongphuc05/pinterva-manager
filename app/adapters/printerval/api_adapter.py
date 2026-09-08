"""PrintervalApiAdapter implements PrintervalAdapter using PrintervalApiClient
for API-first discovery of Waiting orders.

It delegates write operations and detail/asset extraction to an optional fallback
adapter (e.g. PrintervalPlaywrightAdapter) until HTTP endpoints for those operations
have been verified.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

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
    DesignerOptionsResult,
    DiscoverResult,
    OrderDetailResult,
    OrderSummary,
    WriteResult,
)
from app.adapters.printerval.row_mapper import (
    extract_source_asset_url,
    parse_external_order_id,
    parse_order_detail_from_row,
    parse_product_summary_fields,
)


def _checksum_of(web_path: str) -> str | None:
    """download_and_save_image returns a served web path (e.g. "/crawled_assets/
    <platform_id>/<order_id>.png"), not the downloaded bytes — read the file it just
    wrote back to compute the same sha256 checksum the Playwright fallback records."""
    try:
        return hashlib.sha256(Path(web_path.lstrip("/")).read_bytes()).hexdigest()
    except OSError:
        return None


class PrintervalApiAdapter:
    """An API-first adapter that uses server-side HTTP requests for discovering
    Waiting orders, delegating write/detail operations to an optional fallback
    adapter (e.g. Playwright).
    """

    def __init__(
        self,
        api_client: PrintervalApiClient,
        fallback_adapter: PrintervalAdapter | None = None,
        download_images: bool = True,
    ) -> None:
        self.api_client = api_client
        self.fallback_adapter = fallback_adapter
        self.download_images = download_images

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
        if job_type != ALL_JOB_TYPES:
            # Only "all" is a confirmed-safe value for the fast HTTP find endpoint
            # (docs/phase0-field-map.md §4) — every other job_type label is only
            # verified against the live DOM's <select>, via the Playwright fallback's
            # own discover_orders. Guessing an HTTP query value for it risks the exact
            # incident already on record: a mismatched filter string silently returning
            # 0 orders instead of erroring. The Playwright fallback also doesn't (yet)
            # fill the DOM date pickers — date_from/date_to are silently not applied
            # for this path.
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
            page = self.api_client.discover_page(
                status=status,
                page_size=limit,
                page_id=page_id,
                date_from=date_from,
                date_to=date_to,
            )
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
            order_id = parse_external_order_id(row)
            if order_id:
                product_name, sku, category = parse_product_summary_fields(row)

                raw_image_url = extract_image_url_from_dict_or_html(row)
                local_path = (
                    download_and_save_image(order_id, raw_image_url, platform_id=platform_id)
                    if raw_image_url and self.download_images
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
                        sku=sku,
                        product_category=category,
                        designer=(
                            str(row.get("attributes", {}).get("designer_email") or "").strip()
                            if isinstance(row.get("attributes"), dict)
                            else None
                        )
                        or None,
                    )
                )

        next_cursor = str(page_id + 1) if len(page.orders) >= limit else None
        return DiscoverResult(
            success=True,
            orders=discovered,
            cursor=next_cursor,
            total_found=len(discovered),
        )

    def _find_order_row(self, external_order_id: str) -> tuple[dict | None, str | None]:
        """(row, error_class) — row is None on any failure, with error_class set;
        both None only means the order genuinely wasn't found under any known status."""
        try:
            row = self.api_client.find_order(external_order_id)
        except Exception as exc:
            error_cls = (
                exc.error_class.value
                if isinstance(exc, PrintervalApiError)
                else ErrorClass.PERMANENT_EXTERNAL.value
            )
            return None, error_cls
        return row, None

    def list_designer_options(self, external_order_id: str) -> DesignerOptionsResult:
        if self.fallback_adapter:
            return self.fallback_adapter.list_designer_options(external_order_id)
        return DesignerOptionsResult(
            success=False,
            error_class=ErrorClass.PERMANENT_EXTERNAL.value,
            evidence={"message": "No browser adapter provided for Designer options"},
        )

    def get_order_detail(
        self, external_order_id: str, platform_id: str | None = None
    ) -> OrderDetailResult:
        row, error_cls = self._find_order_row(external_order_id)
        if error_cls is not None:
            if self.fallback_adapter:
                return self.fallback_adapter.get_order_detail(external_order_id, platform_id=platform_id)
            return OrderDetailResult(success=False, error_class=error_cls)
        if row is None:
            # Not found under any of the 6 known site statuses — genuinely surprising
            # (an order we ourselves claimed should exist in one of them), fall back to
            # Playwright's own live search rather than guess why.
            if self.fallback_adapter:
                return self.fallback_adapter.get_order_detail(external_order_id, platform_id=platform_id)
            return OrderDetailResult(
                success=False,
                error_class=ErrorClass.EXTERNAL_CHANGED.value,
                evidence={"message": f"order {external_order_id} not found under any known status"},
            )
        return parse_order_detail_from_row(row, external_order_id, platform_id=platform_id)

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
        row, error_cls = self._find_order_row(external_order_id)
        if error_cls is not None:
            if self.fallback_adapter:
                return self.fallback_adapter.download_asset(external_order_id, platform_id=platform_id)
            return AssetResult(
                success=False, external_order_id=external_order_id, error_class=error_cls
            )
        if row is None:
            if self.fallback_adapter:
                return self.fallback_adapter.download_asset(external_order_id, platform_id=platform_id)
            return AssetResult(
                success=False,
                external_order_id=external_order_id,
                error_class=ErrorClass.EXTERNAL_CHANGED.value,
                evidence={"message": f"order {external_order_id} not found under any known status"},
            )

        source_url = extract_source_asset_url(row)
        if not source_url:
            # Only personalized orders have a source file to download — see
            # extract_source_asset_url. Same "success, nothing to download" contract
            # as the Playwright fallback's identical case.
            return AssetResult(success=True, external_order_id=external_order_id)

        local_path = download_and_save_image(external_order_id, source_url, platform_id=platform_id)
        if not local_path:
            return AssetResult(
                success=False,
                external_order_id=external_order_id,
                error_class=ErrorClass.TRANSIENT_NETWORK.value,
                retryable=True,
                evidence={"message": f"failed to download source asset from {source_url}"},
            )
        checksum = _checksum_of(local_path)
        return AssetResult(
            success=True,
            external_order_id=external_order_id,
            local_path=local_path,
            checksum=checksum,
        )
