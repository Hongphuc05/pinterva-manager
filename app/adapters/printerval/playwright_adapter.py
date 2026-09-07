from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.adapters.playwright_support import capture_evidence
from app.adapters.printerval.image_helper import (
    append_to_crawled_orders_csv,
    download_and_save_image,
)
from app.adapters.printerval.interface import ALL_JOB_TYPES
from app.adapters.printerval.models import (
    AssetResult,
    CustomConfig,
    CustomConfigEntry,
    DiscoverResult,
    OrderDetailResult,
    OrderSummary,
    ProductVariant,
    WriteResult,
)

ADMIN_URL = "https://printerval.com/central/outsource/pod/design-job/admin"


class _OrderNotFoundError(Exception):
    """Search completed successfully but no row matched the order id — a
    business validation failure, not adapter/site breakage."""


class _SaveRejectedError(Exception):
    """A write's save request actually completed (unlike a timeout) but the
    server rejected it — a real external outcome, not an adapter bug or a
    retryable network blip. Carries the HTTP status for classification."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _ensure_save_succeeded(resp) -> None:
    """Raise _SaveRejectedError unless a save response is a genuine success.

    Live-confirmed (Task 6 fix round) across all three save endpoints this
    file uses (`/design-job/assign-designer`, `/design-job/update`,
    `/design-job-meta`): a successful save is HTTP 200 with a JSON body
    shaped `{"status": "successful", ...}`. This checks both the HTTP
    status and that body convention — an HTTP failure or an explicit
    non-"successful" body status both count as rejected. A response whose
    body isn't JSON, or is JSON without a "status" key, is treated as fine
    as long as the HTTP status is ok (no error signal available to check).
    """
    if not resp.ok:
        raise _SaveRejectedError(f"HTTP {resp.status}", resp.status)
    try:
        body = resp.json()
    except Exception:
        return
    if isinstance(body, dict) and body.get("status") not in (None, "successful"):
        raise _SaveRejectedError(f"server rejected save: {body}", resp.status)


def _classify_exception(exc: Exception) -> tuple[str, bool]:
    """Map an exception from a read method to (error_class, retryable).

    - PlaywrightTimeoutError: a wait for a selector/response never resolved —
      could just be a slow network, so it's worth a retry.
    - _OrderNotFoundError: the search succeeded but no row matched — not
      retryable, the order genuinely isn't there.
    - LookupError (raised by _find_select_by_option_text, and by the write
      methods' own existence checks before interacting with an expected
      element): an expected element is genuinely missing — the site's
      structure changed, retrying won't help.
    - _SaveRejectedError: the save request completed but the server said no.
      401/403 -> AUTH, 429 -> RATE_LIMIT, 5xx -> TRANSIENT_NETWORK (worth a
      retry), anything else -> PERMANENT_EXTERNAL (a real rejection, not
      retryable, needs a human).
    - anything else: unexpected — treat as a bug rather than guess.
    """
    if isinstance(exc, PlaywrightTimeoutError):
        return "TRANSIENT_NETWORK", True
    if isinstance(exc, _OrderNotFoundError):
        return "VALIDATION", False
    if isinstance(exc, _SaveRejectedError):
        if exc.status in (401, 403):
            return "AUTH", False
        if exc.status == 429:
            return "RATE_LIMIT", True
        if exc.status >= 500:
            return "TRANSIENT_NETWORK", True
        return "PERMANENT_EXTERNAL", False
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
    page.wait_for_load_state("domcontentloaded")
    if "login" in page.url.lower() or page.locator("input[name='username']").count() > 0:
        from app.config import get_settings
        settings = get_settings()
        if settings.printerval_username and settings.printerval_password:
            if page.locator("input[name='username']").count() > 0:
                page.locator("input[name='username']").fill(settings.printerval_username)
            if page.locator("input[name='password']").count() > 0:
                page.locator("input[name='password']").fill(settings.printerval_password)
            submit_btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Đăng nhập')").first
            if submit_btn.count() > 0:
                submit_btn.click()
                page.wait_for_load_state("domcontentloaded")
            page.goto(ADMIN_URL)
            page.wait_for_load_state("domcontentloaded")
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


def _parse_short_datetime(raw: str) -> datetime | None:
    """Parse the "Created at"/"Order created at" format confirmed live 2026-09-07:
    "HH:MM' DD/MM/YYYY" rendered across two lines (e.g. "03:46'\n07/09/2026"). Returns
    None on any mismatch — never guess a different format."""
    tokens = raw.split()
    if len(tokens) != 2:
        return None
    time_part, date_part = tokens
    time_part = time_part.rstrip("'")
    try:
        return datetime.strptime(f"{date_part} {time_part}", "%d/%m/%Y %H:%M")
    except ValueError:
        return None


def _parse_deadline_datetime(raw: str) -> datetime | None:
    """Parse the "Deadline at" format confirmed live 2026-09-07:
    "YYYY-MM-DD HH:MM:SS" — a different format from Created/Order created at on the
    same page."""
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _timestamp_label_text(row, label: str) -> str | None:
    """Text of the <span> next to an exact `<strong>{label}</strong>` block. Uses
    exact text matching (get_by_text(..., exact=True)) — not substring `:has-text` —
    to distinguish "Created at:" from "Order created at:" (a substring match makes
    the shorter label match both), and scopes to the label's own immediate parent
    (not `div:has(...)`, which matches every ancestor and returns the outermost one)
    to avoid grabbing an unrelated span elsewhere in the row."""
    strong = row.get_by_text(label, exact=True)
    if strong.count() == 0:
        return None
    parent = strong.first.locator("xpath=..")
    span = parent.locator("span").first
    if span.count() == 0:
        return None
    return span.inner_text()


def _extract_custom_config(row) -> CustomConfig | None:
    """Live-confirmed structure (2026-09-07): a `.djcfg-card` block (original values)
    and a sibling `.djcfg-card.djcfg-vn` block (Vietnamese translation), each holding
    `.djcfg-row` entries with a `.djcfg-key` label and `.djcfg-val-text` value. Only
    personalized orders have these — absent entirely otherwise."""
    original_rows = row.locator(".djcfg-card:not(.djcfg-vn) .djcfg-row").all()
    if not original_rows:
        return None
    original = [
        CustomConfigEntry(
            key=r.locator(".djcfg-key").inner_text().strip(),
            value=r.locator(".djcfg-val-text").inner_text().strip(),
        )
        for r in original_rows
    ]
    translated_rows = row.locator(".djcfg-card.djcfg-vn .djcfg-row").all()
    translated = [
        CustomConfigEntry(
            key=r.locator(".djcfg-key").inner_text().strip(),
            value=r.locator(".djcfg-val-text").inner_text().strip(),
        )
        for r in translated_rows
    ]
    return CustomConfig(original=original, translated_vn=translated)


def _extract_row_thumbnail_url(row) -> str | None:
    sku_item = row.locator(".product-sku-item").first
    if sku_item.count() > 0:
        img = sku_item.locator(".sb-design-thumbnail img").first
        if img.count() > 0:
            url = img.get_attribute("ng-src") or img.get_attribute("src")
            if url and not any(ignored in url.lower() for ignored in ["flag", "us-flag", "us.png", "icon", "avatar"]):
                return url.strip()

    for img in row.locator("img").all():
        url = img.get_attribute("ng-src") or img.get_attribute("src")
        if url:
            url_lower = url.lower()
            if any(ignored in url_lower for ignored in ["flag", "us-flag", "us.png", "icon", "avatar"]):
                continue
            if any(kw in url_lower for kw in ["assets.printerval", "custom-product", "gdn.printerval", "product", "design", "upload"]):
                return url.strip()
            if url_lower.startswith("http") or url_lower.startswith("//"):
                return url.strip()

    return None


def _extract_row_has_template(row) -> bool:
    if row.locator(".label.label-success:has-text('template')").count() > 0:
        return True
    if row.locator(":has-text('Đã có template')").count() > 0:
        return True
    if row.locator("button[ng-click*='openModalTemplateJob']").count() > 0:
        return True
    if row.locator("button:has-text('template')").count() > 0 or row.locator("button:has-text('Template')").count() > 0:
        return True
    return False


class PlaywrightPrintervalAdapter:
    def __init__(
        self,
        page: Page,
        crawl_username: str | None = None,
        crawl_password: str | None = None,
    ):
        self.page = page
        self.crawl_username = crawl_username
        self.crawl_password = crawl_password

    def discover_orders(
        self,
        status: str,
        job_type: str = ALL_JOB_TYPES,
        limit: int = 40,
        cursor: str | None = None,
        platform_id: str | None = None,
    ) -> DiscoverResult:
        page = self.page
        page.goto(ADMIN_URL)
        page.wait_for_load_state("domcontentloaded")
        if "login" in page.url.lower() or page.locator("input[name='username']").count() > 0 or page.locator("input[name='email']").count() > 0:
            from app.config import get_settings
            settings = get_settings()
            user = self.crawl_username or settings.printerval_username
            pwd = self.crawl_password or settings.printerval_password
            if user and pwd:
                user_input = page.locator("input[name='username'], input[name='email'], input[type='email']").first
                if user_input.count() > 0:
                    user_input.fill(user)
                pass_input = page.locator("input[name='password'], input[type='password']").first
                if pass_input.count() > 0:
                    pass_input.fill(pwd)
                submit_btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Đăng nhập')").first
                if submit_btn.count() > 0:
                    submit_btn.click()
                    page.wait_for_load_state("domcontentloaded")
                page.goto(ADMIN_URL)
                page.wait_for_load_state("domcontentloaded")
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
            order_id = next(
                (tok for tok in text.split() if tok.startswith("DJ") or (tok.isdigit() and len(tok) >= 6)),
                None,
            )
            if order_id is None:
                continue
            selects = row.locator("select")
            designer_value = _selected_option_text(selects.nth(0)) if selects.count() >= 1 else None
            status_value = _selected_option_text(selects.nth(1)) if selects.count() >= 2 else status
            headings = row.locator("h5")
            product_name = headings.first.inner_text().strip() if headings.count() > 0 else ""

            raw_img_url = _extract_row_thumbnail_url(row)
            has_template = _extract_row_has_template(row)

            local_path = (
                download_and_save_image(order_id, raw_img_url, platform_id=platform_id)
                if raw_img_url
                else None
            )
            final_thumbnail = local_path or raw_img_url

            append_to_crawled_orders_csv(
                external_order_id=order_id,
                product_name=product_name,
                status=status_value,
                thumbnail_url=raw_img_url,
                local_image_path=local_path,
                platform_id=platform_id,
            )

            orders.append(
                OrderSummary(
                    external_order_id=order_id,
                    product_name=product_name,
                    designer=designer_value,
                    status=status_value,
                    has_template=has_template,
                    thumbnail_url=final_thumbnail,
                )
            )
        return DiscoverResult(success=True, orders=orders, cursor=None)

    def _extract_order_detail_from_row(self, row, external_order_id: str) -> OrderDetailResult:
        """Extract every OrderDetailResult field from an already-located row."""
        selects = row.locator("select")
        designer = _selected_option_text(selects.nth(0)) if selects.count() >= 1 else None
        status = _selected_option_text(selects.nth(1)) if selects.count() >= 2 else None
        note_group = _note_outsource_group(row)
        note_outsource = (
            note_group.locator("textarea").input_value() if note_group.count() > 0 else ""
        )

        headings = row.locator("h5")
        product_name = headings.first.inner_text().strip() if headings.count() > 0 else None

        sku_item = row.locator(".product-sku-item").first
        thumbnail_url = None
        sku = None
        product_category = None
        product_variants: list[ProductVariant] = []
        if sku_item.count() > 0:
            sku_span = sku_item.locator("[ng-bind='productSku.product_sku']")
            if sku_span.count() > 0:
                sku = sku_span.first.inner_text().strip()
            for line in sku_item.inner_text().splitlines():
                line = line.strip()
                if line.startswith("Category:"):
                    product_category = line[len("Category:") :].strip()
                    break
            for vdiv in sku_item.locator("div[ng-repeat^='variant in productSku.variants']").all():
                line = vdiv.inner_text().strip()
                if " : " in line:
                    name, _, value = line.partition(" : ")
                    product_variants.append(ProductVariant(name=name.strip(), value=value.strip()))

        raw_url = _extract_row_thumbnail_url(row)
        if raw_url:
            local_path = download_and_save_image(external_order_id, raw_url)
            thumbnail_url = local_path or raw_url

        has_template = _extract_row_has_template(row)

        multiple_design_checkbox = row.locator("#multiple-design")
        multiple_design = (
            multiple_design_checkbox.is_checked() if multiple_design_checkbox.count() > 0 else False
        )
        double_sided_checkbox = row.locator("#double-sided")
        double_sided = (
            double_sided_checkbox.is_checked() if double_sided_checkbox.count() > 0 else False
        )

        priority_container = row.locator("div.mt-2")
        priority_span = priority_container.locator("span.label")
        priority_label = (
            priority_span.first.get_attribute("class") if priority_span.count() > 0 else None
        )

        created_at_text = _timestamp_label_text(row, "Created at:")
        order_created_at_text = _timestamp_label_text(row, "Order created at:")
        deadline_text = _timestamp_label_text(row, "Deadline at:")

        order_note_block = row.locator("div.note:has-text('Order note:')")
        order_note = (
            order_note_block.locator(".pre-note").first.inner_text()
            if order_note_block.count() > 0
            else ""
        )

        design_tool_link = row.locator("a[href*='design-tool.printerval.com']")
        design_tool_url = (
            design_tool_link.first.get_attribute("href") if design_tool_link.count() > 0 else None
        )

        template_jobs = None
        if has_template:
            template_jobs = self._extract_template_jobs_from_modal(row)

        return OrderDetailResult(
            success=True,
            external_order_id=external_order_id,
            designer=designer,
            status=status,
            note_outsource=note_outsource,
            order_note=order_note,
            created_at=_parse_short_datetime(created_at_text) if created_at_text else None,
            order_created_at=(
                _parse_short_datetime(order_created_at_text) if order_created_at_text else None
            ),
            deadline_at=_parse_deadline_datetime(deadline_text) if deadline_text else None,
            has_uploaded_design=row.locator(".thumbnail-design-container img").count() > 0,
            product_name=product_name,
            thumbnail_url=thumbnail_url,
            sku=sku,
            product_category=product_category,
            product_variants=product_variants,
            has_template=has_template,
            template_jobs=template_jobs,
            multiple_design=multiple_design,
            double_sided=double_sided,
            priority_label=priority_label,
            custom_config=_extract_custom_config(row),
            design_tool_url=design_tool_url,
        )

    def _extract_template_jobs_from_modal(self, row) -> list[dict] | None:
        btn = row.locator("button[ng-click*='openModalTemplateJob'], button:has-text('Xem template'), button:has-text('template'), button:has-text('Template')").first
        if btn.count() == 0:
            return None
        try:
            btn.click()
            page = self.page
            modal = page.locator(".modal-dialog, .modal-content").first
            modal.wait_for(state="visible", timeout=3000)

            provider_name = None
            note = None
            psd_files: list[dict] = []

            modal_text = modal.inner_text()
            for line in modal_text.splitlines():
                line = line.strip()
                if "Nhà in:" in line or "Nhà in :" in line:
                    provider_name = line.partition(":")[2].strip()
                elif "Note:" in line or "Note :" in line:
                    if not note:
                        note = line.partition(":")[2].strip()

            for link in modal.locator("a[href]").all():
                href = link.get_attribute("href")
                if href and ("drive.google.com" in href or "dropbox" in href or "http" in href):
                    psd_files.append({"url": href.strip()})

            for img in modal.locator("img").all():
                src = img.get_attribute("src") or img.get_attribute("ng-src")
                if src and not any(k in src.lower() for k in ["flag", "icon", "avatar"]):
                    if psd_files:
                        psd_files[0]["image_url"] = src.strip()
                    else:
                        psd_files.append({"image_url": src.strip()})
                    break

            close_btn = modal.locator("button:has-text('Đóng'), button:has-text('Close'), .close").first
            if close_btn.count() > 0:
                close_btn.click()
            else:
                page.keyboard.press("Escape")

            if provider_name or note or psd_files:
                return [{
                    "provider_name": provider_name or "C-EZ",
                    "note": note or "",
                    "psd_file": psd_files if psd_files else []
                }]
        except Exception:
            pass
        return None


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

        try:
            return self._extract_order_detail_from_row(row, external_order_id)
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(
                page, f"get_order_detail_extract_failed_{external_order_id}"
            )
            return OrderDetailResult(
                success=False, error_class=error_class, retryable=retryable, evidence=evidence
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
        try:
            response = page.request.get(src)
            if not response.ok:
                raise _SaveRejectedError(f"HTTP {response.status}", response.status)
            body = response.body()
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, f"download_asset_failed_{external_order_id}")
            return AssetResult(
                success=False, external_order_id=external_order_id,
                error_class=error_class, retryable=retryable, evidence=evidence,
            )
        Path("order_assets").mkdir(exist_ok=True)
        suffix = Path(urlparse(src).path).suffix or ".bin"
        local_path = Path("order_assets") / f"{external_order_id}{suffix}"
        local_path.write_bytes(body)
        checksum = hashlib.sha256(body).hexdigest()
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
            selects = row.locator("select")
            if selects.count() < 1:
                raise LookupError(f"No Designer <select> found for order {external_order_id}")
            designer_select = selects.nth(0)
            if _selected_option_text(designer_select) == designer_option:
                # Already the target value: selecting the same option again
                # fires no real DOM 'change' event (confirmed live), so no
                # save request would ever arrive — expect_response would
                # hang for nothing. Nothing to save; skip straight to the
                # fresh-state confirmation below.
                pass
            else:
                with page.expect_response(
                    lambda r: "/design-job/assign-designer" in r.url
                    and r.request.method == "POST"
                ) as resp_info:
                    designer_select.select_option(label=designer_option, force=True)
                _ensure_save_succeeded(resp_info.value)
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, f"set_designer_failed_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class=error_class, retryable=retryable, evidence=evidence,
            )

        # The save above already succeeded — a failure from here on is "did it
        # really persist?", not "did the write fail?". Per claude.md §8, an
        # unverifiable outcome after a possibly-successful write is
        # UNKNOWN_OUTCOME, never a blind retry candidate and never "order not
        # found".
        try:
            # Genuine fresh-state check: re-navigate/re-search independently
            # rather than trusting the same in-page <select> we just changed
            # — a live incident proved a save can silently not persist while
            # the in-page DOM still looks changed.
            fresh_row = _search_and_get_row(page, external_order_id)
            fresh_selects = fresh_row.locator("select")
            observed = (
                _selected_option_text(fresh_selects.nth(0)) if fresh_selects.count() >= 1 else None
            )
        except Exception:
            evidence = capture_evidence(page, f"set_designer_verify_failed_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class="UNKNOWN_OUTCOME", retryable=False, evidence=evidence,
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
            selects = row.locator("select")
            if selects.count() < 2:
                raise LookupError(f"No Status <select> found for order {external_order_id}")
            status_select = selects.nth(1)
            if _selected_option_text(status_select) == target_status:
                # Already the target value — see set_designer's identical
                # guard for why this must skip the save-response wait.
                pass
            else:
                with page.expect_response(
                    lambda r: "/design-job/update" in r.url and r.request.method == "PATCH"
                ) as resp_info:
                    status_select.select_option(label=target_status, force=True)
                _ensure_save_succeeded(resp_info.value)
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, f"set_status_failed_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class=error_class, retryable=retryable, evidence=evidence,
            )

        # The save above already succeeded — a failure from here on is "did it
        # really persist?", not "did the write fail?". Per claude.md §8, an
        # unverifiable outcome after a possibly-successful write is
        # UNKNOWN_OUTCOME, never a blind retry candidate and never "order not
        # found".
        try:
            # Genuine fresh-state check (see set_designer for why).
            fresh_row = _search_and_get_row(page, external_order_id)
            fresh_selects = fresh_row.locator("select")
            observed = (
                _selected_option_text(fresh_selects.nth(1)) if fresh_selects.count() >= 2 else None
            )
        except Exception:
            evidence = capture_evidence(page, f"set_status_verify_failed_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class="UNKNOWN_OUTCOME", retryable=False, evidence=evidence,
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
            if note_group.count() == 0:
                raise LookupError(f"No Note outsource field found for order {external_order_id}")
            textarea = note_group.locator("textarea")
            if textarea.count() == 0:
                raise LookupError(f"No note textarea found for order {external_order_id}")
            if textarea.input_value() == drive_url:
                # Already the target value (reading the textarea's real
                # ng-model value works even while hidden, no dblclick
                # needed). Clicking Save would still fire a real write —
                # unlike the two <select>s, this button has no "did the
                # value change" guard — so restore_order's unconditional
                # call would otherwise perform a redundant live write on
                # every single smoke test, on the exact field that already
                # caused a real incident this session. Skip straight to the
                # fresh-state confirmation below.
                pass
            else:
                note_group.dblclick()
                textarea.fill(drive_url)
                with page.expect_response(
                    lambda r: "/design-job-meta" in r.url and r.request.method == "POST"
                ) as resp_info:
                    note_group.get_by_role("button", name="Save").click()
                _ensure_save_succeeded(resp_info.value)
        except Exception as exc:
            error_class, retryable = _classify_exception(exc)
            evidence = capture_evidence(page, f"attach_result_link_failed_{external_order_id}")
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class=error_class, retryable=retryable, evidence=evidence,
            )

        # The save above already succeeded — a failure from here on is "did it
        # really persist?", not "did the write fail?". Per claude.md §8, an
        # unverifiable outcome after a possibly-successful write is
        # UNKNOWN_OUTCOME, never a blind retry candidate and never "order not
        # found".
        try:
            # Genuine fresh-state check: re-navigate/re-search independently
            # instead of trusting the same in-page textarea we just filled —
            # this is exactly the check that caught the original incident,
            # where the save silently didn't persist while the in-page
            # textarea still showed the new value.
            fresh_row = _search_and_get_row(page, external_order_id)
            observed = _note_outsource_group(fresh_row).locator("textarea").input_value()
        except Exception:
            evidence = capture_evidence(
                page, f"attach_result_link_verify_failed_{external_order_id}"
            )
            return WriteResult(
                success=False, external_order_id=external_order_id,
                error_class="UNKNOWN_OUTCOME", retryable=False, evidence=evidence,
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
