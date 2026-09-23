from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Settings

LOGIN_PATH = "/outsource/pod/login"
FIND_PATH = "/outsource/pod/design-job/find"
ADMIN_PATH = "/central/outsource/pod/design-job/admin"


class PrintervalConfigurationError(ValueError):
    """The read-only Printerval client is missing required configuration."""


class PrintervalApiError(RuntimeError):
    def __init__(self, error_code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class _HiddenInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        values = dict(attrs)
        if values.get("type", "").lower() == "hidden" and values.get("name"):
            self.fields[str(values["name"])] = values.get("value") or ""


@dataclass(frozen=True)
class PrintervalPage:
    status: str
    page_id: int
    rows: list[dict[str, Any]]
    raw: dict[str, Any]

    @property
    def total_count(self) -> int | None:
        return _metadata_int(self.raw, "total_count")

    @property
    def page_count(self) -> int | None:
        return _metadata_int(self.raw, "page_count")


def _metadata_int(payload: dict[str, Any], key: str) -> int | None:
    for container in (payload.get("meta"), payload.get("metadata"), payload):
        if not isinstance(container, dict):
            continue
        value = container.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def _classify_status(status_code: int) -> tuple[str, bool]:
    if status_code in (401, 403):
        return "auth", False
    if status_code == 429:
        return "rate_limit", True
    if status_code >= 500:
        return "transient_network", True
    return "external_changed", False


class PrintervalClient:
    """Read-only client for the same API path used by the production Waiting crawl."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        settings.validate_printerval_auth()
        if not settings.printerval_team_outsource.strip():
            raise PrintervalConfigurationError("PRINTERVAL_TEAM_OUTSOURCE is required")

        self.settings = settings
        self.base_url = settings.printerval_api_base_url.rstrip("/")
        self.team_outsource = settings.printerval_team_outsource.strip()
        self.session_cookie = settings.printerval_session_cookie.strip() if settings.printerval_session_cookie else None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self.session_cookie:
            headers["Cookie"] = self._cookie_header(self.session_cookie)
        self._client = client or httpx.Client(
            base_url=self.base_url,
            follow_redirects=False,
            timeout=httpx.Timeout(settings.printerval_timeout_seconds),
            headers=headers,
        )
        self._authenticated = False

    @staticmethod
    def _cookie_header(value: str) -> str:
        clean = value.strip().strip('"').strip("'")
        if clean.lower().startswith("cookie:"):
            clean = clean[7:].strip()
        if "laravel_session=" in clean or (";" in clean and "=" in clean):
            return clean
        return f"laravel_session={clean}"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PrintervalClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _hidden_fields(html: str) -> dict[str, str]:
        parser = _HiddenInputParser()
        parser.feed(html)
        return parser.fields

    def login(self) -> None:
        if self.session_cookie:
            probe = self._request_find(
                {
                    "page_size": "1",
                    "page_id": "0",
                    "status": "waiting",
                    "team_outsource": self.team_outsource,
                }
            )
            if probe.status_code == 200 and self._is_successful_json(probe):
                self._authenticated = True
                return
            raise PrintervalApiError(
                "auth",
                "PRINTERVAL_SESSION_COOKIE is invalid or expired; provide a fresh complete cookie",
            )

        if not self.settings.printerval_username or not self.settings.printerval_password:
            raise PrintervalConfigurationError(
                "Set PRINTERVAL_SESSION_COOKIE or PRINTERVAL_USERNAME/PRINTERVAL_PASSWORD"
            )
        try:
            form_page = self._client.get(LOGIN_PATH, params={"redirect": ADMIN_PATH})
        except httpx.HTTPError as exc:
            raise PrintervalApiError("transient_network", "Could not open Printerval login form", retryable=True) from exc
        if form_page.status_code >= 400:
            code, retryable = _classify_status(form_page.status_code)
            raise PrintervalApiError(code, "Printerval rejected the login form", retryable=retryable)

        form = self._hidden_fields(form_page.text)
        token = form.get("_token")
        if not token:
            raise PrintervalApiError("external_changed", "Printerval login form has no CSRF token")
        form.update(
            {
                "_token": token,
                "redirect": form.get("redirect") or ADMIN_PATH,
                "username": self.settings.printerval_username,
                "password": self.settings.printerval_password,
                "remember": "1",
            }
        )
        try:
            response = self._client.post(LOGIN_PATH, data=form)
        except httpx.HTTPError as exc:
            raise PrintervalApiError("transient_network", "Printerval login request failed", retryable=True) from exc
        if response.status_code not in (200, 301, 302, 303, 307, 308):
            code, retryable = _classify_status(response.status_code)
            raise PrintervalApiError(code, "Printerval rejected the supplied login", retryable=retryable)
        location = response.headers.get("location", "")
        if response.status_code in (301, 302, 303, 307, 308) and LOGIN_PATH in urlparse(location).path:
            raise PrintervalApiError("auth", "Printerval did not accept the supplied login")
        self._authenticated = True

    def fetch_page(self, *, status: str, page_id: int, page_size: int = 100) -> PrintervalPage:
        if status not in {"done", "confirm", "review", "fix"}:
            raise ValueError(f"Unsupported historical status: {status}")
        if page_id < 0:
            raise ValueError("page_id must be non-negative")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if not self._authenticated:
            self.login()

        params = {
            "page_size": str(page_size),
            "page_id": str(page_id),
            "status": status,
            "time_type": "created_at",
            "job_type": "all",
            "team_outsource": self.team_outsource,
        }
        response = self._request_find_with_reauthentication(params)
        if response.status_code >= 400:
            code, retryable = _classify_status(response.status_code)
            raise PrintervalApiError(code, f"Printerval {status} page was rejected", retryable=retryable)
        try:
            payload = response.json()
        except ValueError as exc:
            raise PrintervalApiError("external_changed", "Printerval response was not JSON") from exc
        if not isinstance(payload, dict) or payload.get("status") != "successful":
            raise PrintervalApiError("external_changed", "Printerval response envelope changed or failed")
        rows = payload.get("result")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise PrintervalApiError("external_changed", "Printerval response has an invalid result list")
        return PrintervalPage(status=status, page_id=page_id, rows=rows, raw=payload)

    def _request_find(self, params: dict[str, str]) -> httpx.Response:
        try:
            return self._client.get(FIND_PATH, params=params)
        except httpx.HTTPError as exc:
            raise PrintervalApiError("transient_network", "Printerval find request failed", retryable=True) from exc

    def _request_find_with_reauthentication(self, params: dict[str, str]) -> httpx.Response:
        response = self._request_find(params)
        redirected_to_login = (
            response.status_code in (301, 302, 303, 307, 308)
            and LOGIN_PATH in urlparse(response.headers.get("location", "")).path
        )
        if response.status_code not in (401, 403) and not redirected_to_login:
            return response

        self._authenticated = False
        self.login()
        return self._request_find(params)

    @staticmethod
    def _is_successful_json(response: httpx.Response) -> bool:
        content_type = response.headers.get("content-type", "").lower()
        if response.status_code != 200 and "application/json" not in content_type:
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        return isinstance(payload, dict) and payload.get("status") == "successful"
