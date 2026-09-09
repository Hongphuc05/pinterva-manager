"""Small, server-side HTTP client for Printerval's outsource API.

This module deliberately implements only authentication and the read-only Waiting
queue.  Claiming an order, fetching its detail, and downloading its source image
remain on the verified browser adapter until their HTTP contracts have been
captured and tested.  Keeping that boundary explicit prevents a Refresh from
silently producing orders without their required images.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from app.adapters.errors import ErrorClass

LOGIN_PATH = "/outsource/pod/login"
FIND_PATH = "/outsource/pod/design-job/find"
ADMIN_PATH = "/central/outsource/pod/design-job/admin"
DESIGNER_OPTIONS_URL = "https://central.api.printerval.com/designer_outsource"


class PrintervalApiConfigurationError(ValueError):
    """The API crawl was requested without all required server configuration."""


class PrintervalApiError(RuntimeError):
    """A classified, non-secret failure from Printerval's HTTP interface."""

    def __init__(self, error_class: ErrorClass, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.error_class = error_class
        self.retryable = retryable


class _HiddenInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        values = dict(attrs)
        name = values.get("name")
        if name and values.get("type", "").lower() == "hidden":
            self.fields[name] = values.get("value") or ""


@dataclass(frozen=True)
class PrintervalApiPage:
    """One validated page from the read-only design-job endpoint."""

    orders: list[dict[str, Any]]
    raw: dict[str, Any]


def _classify_http_status(status_code: int) -> tuple[ErrorClass, bool]:
    if status_code in (401, 403):
        return ErrorClass.AUTH, False
    if status_code == 429:
        return ErrorClass.RATE_LIMIT, True
    if status_code >= 500:
        return ErrorClass.TRANSIENT_NETWORK, True
    return ErrorClass.PERMANENT_EXTERNAL, False


class PrintervalApiClient:
    """Authenticates with a CSRF form and reads only `status=waiting` jobs."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str | None,
        password: str | None,
        team_outsource: str | None,
        session_cookie: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.team_outsource = team_outsource
        self.session_cookie = session_cookie.strip() if session_cookie and session_cookie.strip() else None

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self.session_cookie:
            c_val = self.session_cookie.strip().strip('"').strip("'")
            if c_val.lower().startswith("cookie:"):
                c_val = c_val[7:].strip()
            if "=" not in c_val:
                c_val = f"laravel_session={c_val}"
            headers["Cookie"] = c_val

        self._client = client or httpx.Client(
            base_url=self.base_url,
            follow_redirects=False,
            timeout=httpx.Timeout(30.0),
            headers=headers,
        )
        self._authenticated = False
        self._designer_map_cache: dict[str, str] | None = None
        self._designer_options_cache: list[str] | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PrintervalApiClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _validate_configuration(self) -> None:
        if not self.team_outsource or not self.team_outsource.strip():
            raise PrintervalApiConfigurationError(
                "Printerval API crawl is not configured: PRINTERVAL_TEAM_OUTSOURCE"
            )
        if not self.session_cookie and (not self.username or not self.password):
            raise PrintervalApiConfigurationError(
                "Printerval API crawl requires either a Session Cookie or Username/Password"
            )

    @staticmethod
    def _hidden_fields(html: str) -> dict[str, str]:
        parser = _HiddenInputParser()
        parser.feed(html)
        return parser.fields

    def login(self) -> None:
        self._validate_configuration()
        if self.session_cookie:
            # Validate existing session cookie via lightweight API call
            try:
                test_res = self._client.get(
                    FIND_PATH,
                    params={
                        "page_size": "1",
                        "page_id": "0",
                        "status": "waiting",
                        "team_outsource": self.team_outsource or "",
                    },
                )
                redirected_to_login = (
                    test_res.status_code in (301, 302, 303, 307, 308)
                    and LOGIN_PATH in urlparse(test_res.headers.get("location", "")).path
                )
                is_json = (
                    "application/json" in test_res.headers.get("content-type", "").lower()
                    or test_res.text.strip().startswith("{")
                )
                if test_res.status_code == 200 and not redirected_to_login and is_json:
                    self._authenticated = True
                    return
            except httpx.HTTPError:
                pass
            # If session cookie probe failed, do not fall back to form login on Cloud datacenter IPs
            # because form login will be blocked by Cloudflare WAF 403 anyway.
            raise PrintervalApiError(
                ErrorClass.AUTH,
                "Session Cookie Printerval không hợp lệ hoặc đã hết hạn (hoặc dán thiếu/bị cắt ngắn). Vui lòng F12 lấy lại Cookie mới đầy đủ.",
            )

        try:
            form_page = self._client.get(LOGIN_PATH, params={"redirect": ADMIN_PATH})
        except httpx.HTTPError as exc:
            raise PrintervalApiError(
                ErrorClass.TRANSIENT_NETWORK, "Could not open login form", retryable=True
            ) from exc
        if form_page.status_code >= 400:
            error_class, retryable = _classify_http_status(form_page.status_code)
            raise PrintervalApiError(error_class, "Login form was rejected", retryable=retryable)

        form = self._hidden_fields(form_page.text)
        token = form.get("_token")
        if not token:
            raise PrintervalApiError(ErrorClass.EXTERNAL_CHANGED, "Login form has no CSRF token")
        form.update(
            {
                "_token": token,
                "redirect": form.get("redirect") or ADMIN_PATH,
                "username": self.username or "",
                "password": self.password or "",
                "remember": "1",
            }
        )
        try:
            response = self._client.post(LOGIN_PATH, data=form)
        except httpx.HTTPError as exc:
            raise PrintervalApiError(
                ErrorClass.TRANSIENT_NETWORK, "Login request failed", retryable=True
            ) from exc
        if response.status_code not in (200, 301, 302, 303, 307, 308):
            error_class, retryable = _classify_http_status(response.status_code)
            raise PrintervalApiError(
                error_class, "Printerval rejected the login", retryable=retryable
            )
        location = response.headers.get("location", "")
        if (
            response.status_code in (301, 302, 303, 307, 308)
            and LOGIN_PATH in urlparse(location).path
        ):
            raise PrintervalApiError(
                ErrorClass.AUTH, "Printerval did not accept the supplied login"
            )
        self._authenticated = True

    def discover_page(
        self,
        *,
        status: str = "waiting",
        page_size: int = 40,
        page_id: int = 0,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> PrintervalApiPage:
        """Fetch one page of jobs for a confirmed Printerval status, read-only.

        date_from/date_to (each "YYYY-MM-DD HH:MM:SS", filtering on `created_at`) are
        live-confirmed 2026-09-08 by reading the site's own controller JS
        (design-job-outsource-controller.js's buildUrl) for the real param names and
        format, then verified empirically: a far-future date_from and a far-past
        date_to each returned 0 rows, and a real recent date_from returned a
        different row set than no filter at all.
        """
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if page_id < 0:
            raise ValueError("page_id must be non-negative")
        params = {
            "page_size": str(page_size),
            "page_id": str(page_id),
            "status": status.lower(),
            "time_type": "created_at",
            "job_type": "all",
            "team_outsource": self.team_outsource or "",
        }
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        result = self._fetch_find_rows(params, error_context=f"{status} queue")
        return PrintervalApiPage(orders=result, raw={"status": "successful", "result": result})

    def discover_waiting_page(self, **kwargs) -> PrintervalApiPage:
        """Compatibility wrapper for existing Waiting-only callers."""
        return self.discover_page(status="waiting", **kwargs)

    #: The site's 6 real order statuses (docs/phase0-field-map.md §1), confirmed live
    #: 2026-09-08 as the exact literal values this endpoint's own `status` param
    #: accepts (lowercase of the DOM label) — each one returned rows whose own
    #: `status` field echoed back that same value. "doing" first: find_order is only
    #: ever called right after this app's own claim, so that's overwhelmingly the
    #: common case.
    ORDER_STATUSES = ("doing", "waiting", "review", "fix", "confirm", "done")

    def find_order(
        self, external_order_id: str, statuses: tuple[str, ...] = ORDER_STATUSES
    ) -> dict[str, Any] | None:
        """Fetch one order's full row via the site's own `search=` filter — Live-
        confirmed 2026-09-08: `search=<DJ code>` matches by exact code, but only
        together with a `status` that exactly matches the order's current site
        status (a mismatched status returns 0 rows, not an error) — hence trying
        each candidate status in turn until one matches. Read-only, same endpoint
        `discover_waiting_page` already uses, just scoped to one order instead of a
        page. Returns the raw row dict, or None if not found under any of them.

        Verifies the returned row's own numeric `id` actually matches the requested
        order before trusting it — live incident 2026-09-08: for a status that isn't
        the order's real current status, the endpoint doesn't always reliably return
        zero rows as documented above; it was observed to instead return an unrelated
        order's row (page 1 of that status, `search` silently not applied), which
        `_fetch_find_rows` has no way to tell apart from a real match by shape alone.
        Blindly trusting `rows[0]` overwrote one order's product/deadline/source files
        with a completely different order's data. A mismatch is treated exactly like
        an empty result — keep trying the remaining statuses.
        """
        code = (
            external_order_id
            if external_order_id.upper().startswith("DJ")
            else f"DJ{external_order_id}"
        )
        numeric_id = code[2:] if code.upper().startswith("DJ") else code
        for status in statuses:
            params = {
                "page_size": "1",
                "page_id": "0",
                "status": status,
                "time_type": "created_at",
                "job_type": "all",
                "team_outsource": self.team_outsource or "",
                "search": code,
            }
            rows = self._fetch_find_rows(params, error_context="Order search")
            if rows and str(rows[0].get("id")) == numeric_id:
                return rows[0]
        return None

    def get_designer_options_raw(self) -> list[dict[str, Any]]:
        """Fetch raw designer rows for this client's team outsource."""
        self._validate_configuration()
        try:
            response = self._client.get(
                DESIGNER_OPTIONS_URL,
                params={"page_size": "-1", "filters": f"team={self.team_outsource}"},
            )
        except httpx.HTTPError as exc:
            raise PrintervalApiError(
                ErrorClass.TRANSIENT_NETWORK,
                "Designer options request failed",
                retryable=True,
            ) from exc
        if response.status_code in (401, 403):
            try:
                self.login()
                response = self._client.get(
                    DESIGNER_OPTIONS_URL,
                    params={"page_size": "-1", "filters": f"team={self.team_outsource}"},
                )
            except Exception:
                pass
        if response.status_code >= 400:
            error_class, retryable = _classify_http_status(response.status_code)
            raise PrintervalApiError(
                error_class,
                "Designer options request was rejected",
                retryable=retryable,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED,
                "Designer options response was not JSON",
            ) from exc
        rows = payload.get("result") if isinstance(payload, dict) else None
        if payload.get("status") != "successful" or not isinstance(rows, list):
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED,
                "Designer options response changed or was rejected",
            )
        return [r for r in rows if isinstance(r, dict)]

    def get_designer_map(self) -> dict[str, str]:
        """Return a mapping of email (lowercased) -> full_name for team designers."""
        if self._designer_map_cache is not None:
            return self._designer_map_cache
        try:
            rows = self.get_designer_options_raw()
            mapping: dict[str, str] = {}
            for r in rows:
                email = str(r.get("email") or "").strip().lower()
                full_name = str(r.get("full_name") or "").strip()
                if email and full_name:
                    mapping[email] = full_name
            self._designer_map_cache = mapping
            return mapping
        except Exception:
            return {}

    def list_designer_options(self) -> list[str]:
        """Read Designer labels for this client's own outsourced team via HTTP."""
        if self._designer_options_cache is not None:
            return self._designer_options_cache
        rows = self.get_designer_options_raw()
        options = list(
            dict.fromkeys(
                name.strip()
                for row in rows
                if isinstance((name := row.get("full_name")), str)
                and name.strip()
            )
        )
        if not options:
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED,
                "Designer options response had no usable Designer",
            )
        self._designer_options_cache = options
        return options

    def _fetch_find_rows(self, params: dict[str, str], *, error_context: str) -> list[dict[str, Any]]:
        """Shared GET+validate+parse for `/design-job/find` — used by both the
        Waiting-queue page fetch and the single-order search."""
        self._validate_configuration()
        response = self._find_with_one_reauthentication(params)
        if response.status_code >= 400:
            error_class, retryable = _classify_http_status(response.status_code)
            raise PrintervalApiError(
                error_class, f"{error_context} request was rejected", retryable=retryable
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED, f"{error_context} was not JSON"
            ) from exc
        if not isinstance(payload, dict) or payload.get("status") != "successful":
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED, f"{error_context} response changed or was rejected"
            )
        result = payload.get("result")
        if not isinstance(result, list):
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED, f"{error_context} has no result list"
            )
        if not all(isinstance(item, dict) for item in result):
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED, f"{error_context} contains an invalid row"
            )
        return result

    def _find_with_one_reauthentication(self, params: dict[str, str]) -> httpx.Response:
        try:
            response = self._client.get(FIND_PATH, params=params)
        except httpx.HTTPError as exc:
            raise PrintervalApiError(
                ErrorClass.TRANSIENT_NETWORK, "Waiting queue request failed", retryable=True
            ) from exc
        redirected_to_login = (
            response.status_code in (301, 302, 303, 307, 308)
            and LOGIN_PATH in urlparse(response.headers.get("location", "")).path
        )
        if response.status_code not in (401, 403) and not redirected_to_login:
            return response
        self._authenticated = False
        try:
            self.login()
        except PrintervalApiError:
            pass
        try:
            return self._client.get(FIND_PATH, params=params)
        except httpx.HTTPError as exc:
            raise PrintervalApiError(
                ErrorClass.TRANSIENT_NETWORK, "Waiting queue retry failed", retryable=True
            ) from exc
