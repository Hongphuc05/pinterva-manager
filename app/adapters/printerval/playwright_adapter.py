from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.adapters.playwright_support import capture_evidence
from app.adapters.printerval.models import (
    AssetResult,
    DiscoverResult,
    OrderDetailResult,
    OrderSummary,
    WriteResult,
)

ADMIN_URL = "https://printerval.com/central/outsource/pod/design-job/admin"


class _OrderNotFoundError(Exception):
    """Search completed successfully but no row matched the order id — a
    business validation failure, not adapter/site breakage."""


def _classify_exception(exc: Exception) -> tuple[str, bool]:
    """Map an exception from a read method to (error_class, retryable).

    - PlaywrightTimeoutError: a wait for a selector/response never resolved —
      could just be a slow network, so it's worth a retry.
    - _OrderNotFoundError: the search succeeded but no row matched — not
      retryable, the order genuinely isn't there.
    - LookupError (raised by _find_select_by_option_text): an expected
      <select>/option is genuinely missing — the site's structure changed,
      retrying won't help.
    - anything else: unexpected — treat as a bug rather than guess.
    """
    if isinstance(exc, PlaywrightTimeoutError):
        return "TRANSIENT_NETWORK", True
    if isinstance(exc, _OrderNotFoundError):
        return "VALIDATION", False
    if isinstance(exc, LookupError):
        return "EXTERNAL_CHANGED", False
    return "BUG", False


def _find_select_by_option_text(page: Page, expected_option_text: str):
    """Locate a <select> by one of its option texts (stable — independent of
    position on the page, unlike an index-based selector).

    Exact match (after strip), not substring: Task 6 found live that a
    substring match is ambiguous under some accounts — e.g. a Designer
    filter option literally named "Nguyễn Thị Thuý Hường - 2D Prin" contains
    the substring "2D" and would shadow the real job-type "2D" option
    (which comes later in DOM order), making a substring search pick the
    wrong <select>.
    """
    for select in page.locator("select").all():
        options_text = select.locator("option").all_inner_texts()
        if any(opt.strip() == expected_option_text for opt in options_text):
            return select
    raise LookupError(
        f"No <select> found with an option exactly matching {expected_option_text!r}"
    )


def _selected_option_text(select) -> str | None:
    """Visible label of a <select>'s selected option.

    Live-DOM finding: this site's per-row Designer/Status <select>s carry opaque
    `.value` attributes (e.g. "object:72", "string:someone@gmail.com") — the
    human-readable label ("Confirm", a designer's display name) lives only on
    the selected <option>'s text, not the value.
    """
    return select.evaluate(
        "el => el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : null"
    )


def _note_outsource_group(row):
    """Locate the row's live "Note outsource" field group.

    Real-DOM finding (Task 6, re-verified under the current team's account):
    a row renders two `.note` groups sharing the same "Note outsource" label —
    one for the regular design-job flow (`aria-hidden="false"`), one for the
    separate "find-design" sub-workflow (`aria-hidden="true"`, out of scope
    here). `[aria-hidden='false']` disambiguates them. This field is an
    Angular double-click-to-edit control: the textarea (`ng-model=
    "item.attributes.outsource_note"`) is hidden until the group is
    double-clicked, and a "Save" button (`ng-click="saveAttribute(item,
    'outsource_note')"`) persists it. Confirmed live: across 8 sampled real
    `Done` orders, this field already holds a human-pasted Google Drive
    result-link URL in every case — this is the real, in-use mechanism for
    attaching a designer's result link, not the file-upload widget.
    """
    return row.locator(".note[aria-hidden='false']").first


def _search_and_get_row(page: Page, external_order_id: str):
    """Navigate to the admin page and search for one order by its DJ code
    across all statuses, returning its table row.

    Self-contained (always starts from a fresh page load) rather than assuming
    a particular filter is already applied — the live admin page shows an
    empty table until a search is actually run, so any read of a single order
    must trigger its own search regardless of what a prior discover_orders
    call may have left the page showing.
    """
    page.goto(ADMIN_URL)
    page.wait_for_load_state("networkidle")
    page.get_by_placeholder("Search products...").fill(external_order_id)
    status_select = _find_select_by_option_text(page, "All status")
    status_select.select_option(label="All status", force=True)
    with page.expect_response(lambda r: "/design-job/find" in r.url):
        page.get_by_role("button", name="Search").click()
    row = page.locator(f"tr:has-text('{external_order_id}')").first
    try:
        row.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError:
        # Same grace period the row always got — only now, after it has
        # elapsed, do we check whether the row is genuinely absent (vs. some
        # other rendering hiccup, which should stay a retryable timeout).
        if row.count() == 0:
            raise _OrderNotFoundError(
                f"No row found for order {external_order_id} after search"
            ) from None
        raise
    return row


class PlaywrightPrintervalAdapter:
    def __init__(self, page: Page):
        self.page = page

    def discover_orders(
        self,
        status: str,
        job_type: str = "2D",
        limit: int = 40,
        cursor: str | None = None,
    ) -> DiscoverResult:
        page = self.page
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")
        try:
            status_select = _find_select_by_option_text(page, status)
            status_select.select_option(label=status, force=True)
            job_type_select = _find_select_by_option_text(page, job_type)
            job_type_select.select_option(label=job_type, force=True)
            with page.expect_response(lambda r: "/design-job/find" in r.url):
                page.get_by_role("button", name="Search").click()
            page.wait_for_timeout(500)
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, "discover_orders_filter_failed")
            return DiscoverResult(
                success=False, error_class=error_class, retryable=retryable, evidence=evidence
            )

        rows = page.locator("tbody.list-order-contain tr").all()
        orders: list[OrderSummary] = []
        for row in rows[:limit]:
            text = row.inner_text()
            order_id = next((tok for tok in text.split() if tok.startswith("DJ")), None)
            if order_id is None:
                continue
            selects = row.locator("select")
            designer_value = _selected_option_text(selects.nth(0)) if selects.count() >= 1 else None
            status_value = _selected_option_text(selects.nth(1)) if selects.count() >= 2 else status
            headings = row.locator("h5")
            product_name = headings.first.inner_text().strip() if headings.count() > 0 else ""
            orders.append(
                OrderSummary(
                    external_order_id=order_id,
                    product_name=product_name,
                    designer=designer_value,
                    status=status_value,
                )
            )
        return DiscoverResult(success=True, orders=orders, cursor=None)

    def get_order_detail(self, external_order_id: str) -> OrderDetailResult:
        page = self.page
        try:
            row = _search_and_get_row(page, external_order_id)
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, f"get_order_detail_missing_{external_order_id}")
            return OrderDetailResult(
                success=False, error_class=error_class, retryable=retryable, evidence=evidence
            )

        selects = row.locator("select")
        designer = _selected_option_text(selects.nth(0)) if selects.count() >= 1 else None
        status = _selected_option_text(selects.nth(1)) if selects.count() >= 2 else None
        return OrderDetailResult(
            success=True,
            external_order_id=external_order_id,
            designer=designer,
            status=status,
            has_uploaded_design=row.locator(".thumbnail-design-container img").count() > 0,
        )

    def download_asset(self, external_order_id: str) -> AssetResult:
        page = self.page
        try:
            row = _search_and_get_row(page, external_order_id)
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, f"download_asset_missing_{external_order_id}")
            return AssetResult(
                success=False,
                external_order_id=external_order_id,
                error_class=error_class,
                retryable=retryable,
                evidence=evidence,
            )

        link = row.locator("a.djcfg-src-link").first
        if link.count() == 0:
            return AssetResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        src = link.get_attribute("href")
        response = page.request.get(src)
        Path("order_assets").mkdir(exist_ok=True)
        suffix = Path(urlparse(src).path).suffix or ".bin"
        local_path = Path("order_assets") / f"{external_order_id}{suffix}"
        local_path.write_bytes(response.body())
        checksum = hashlib.sha256(response.body()).hexdigest()
        return AssetResult(
            success=True,
            external_order_id=external_order_id,
            local_path=str(local_path),
            checksum=checksum,
        )

    def set_designer(self, external_order_id: str, designer_option: str) -> WriteResult:
        page = self.page
        try:
            row = _search_and_get_row(page, external_order_id)
            designer_select = row.locator("select").nth(0)
            designer_select.select_option(label=designer_option, force=True)
            observed = _selected_option_text(designer_select)
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, f"set_designer_failed_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class=error_class, retryable=retryable, evidence=evidence,
            )
        if observed != designer_option:
            evidence = capture_evidence(page, f"set_designer_unverified_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class="UNKNOWN_OUTCOME", retryable=False, evidence=evidence,
                observed_state={"designer": observed},
            )
        return WriteResult(
            success=True, external_order_id=external_order_id,
            observed_state={"designer": observed},
        )

    def set_status(self, external_order_id: str, target_status: str) -> WriteResult:
        page = self.page
        try:
            row = _search_and_get_row(page, external_order_id)
            status_select = row.locator("select").nth(1)
            status_select.select_option(label=target_status, force=True)
            observed = _selected_option_text(status_select)
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, f"set_status_failed_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class=error_class, retryable=retryable, evidence=evidence,
            )
        if observed != target_status:
            evidence = capture_evidence(page, f"set_status_unverified_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class="UNKNOWN_OUTCOME", retryable=False, evidence=evidence,
                observed_state={"status": observed},
            )
        return WriteResult(
            success=True, external_order_id=external_order_id,
            observed_state={"status": observed},
        )

    def attach_result_link(self, external_order_id: str, drive_url: str) -> WriteResult:
        page = self.page
        try:
            row = _search_and_get_row(page, external_order_id)
            note_group = _note_outsource_group(row)
            note_group.dblclick()
            textarea = note_group.locator("textarea")
            textarea.fill(drive_url)
            with page.expect_response(
                lambda r: "/design-job-meta" in r.url and r.request.method == "POST"
            ):
                note_group.get_by_role("button", name="Save").click()
            observed = textarea.input_value()
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, f"attach_result_link_failed_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class=error_class, retryable=retryable, evidence=evidence,
            )
        if observed != drive_url:
            evidence = capture_evidence(page, f"attach_result_link_unverified_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class="UNKNOWN_OUTCOME", retryable=False, evidence=evidence,
                observed_state={"result_link": observed},
            )
        return WriteResult(
            success=True, external_order_id=external_order_id,
            observed_state={"result_link": observed},
        )
