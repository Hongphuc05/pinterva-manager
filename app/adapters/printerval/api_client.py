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
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.team_outsource = team_outsource
        self._client = client or httpx.Client(
            base_url=self.base_url,
            follow_redirects=False,
            timeout=httpx.Timeout(30.0),
            headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (compatible; PintervalOps/1.0)",
            },
        )
        self._authenticated = False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PrintervalApiClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _validate_configuration(self) -> None:
        missing = [
            name
            for name, value in (
                ("PRINTERVAL_USERNAME", self.username),
                ("PRINTERVAL_PASSWORD", self.password),
                ("PRINTERVAL_TEAM_OUTSOURCE", self.team_outsource),
            )
            if value is None or not str(value).strip()
        ]
        if missing:
            raise PrintervalApiConfigurationError(
                "Printerval API crawl is not configured: " + ", ".join(missing)
            )

    @staticmethod
    def _hidden_fields(html: str) -> dict[str, str]:
        parser = _HiddenInputParser()
        parser.feed(html)
        return parser.fields

    def login(self) -> None:
        self._validate_configuration()
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

    def discover_waiting_page(self, *, page_size: int = 40, page_id: int = 0) -> PrintervalApiPage:
        """Fetch one page of Waiting jobs without modifying any external order."""
        self._validate_configuration()
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if page_id < 0:
            raise ValueError("page_id must be non-negative")
        if not self._authenticated:
            self.login()

        params = {
            "page_size": str(page_size),
            "page_id": str(page_id),
            "status": "waiting",
            "time_type": "created_at",
            "job_type": "all",
            "team_outsource": self.team_outsource or "",
        }
        response = self._find_with_one_reauthentication(params)
        if response.status_code >= 400:
            error_class, retryable = _classify_http_status(response.status_code)
            raise PrintervalApiError(
                error_class, "Waiting queue request was rejected", retryable=retryable
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED, "Waiting queue was not JSON"
            ) from exc
        if not isinstance(payload, dict) or payload.get("status") != "successful":
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED, "Waiting queue response changed or was rejected"
            )
        result = payload.get("result")
        if not isinstance(result, list):
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED, "Waiting queue has no result list"
            )
        if not all(isinstance(item, dict) for item in result):
            raise PrintervalApiError(
                ErrorClass.EXTERNAL_CHANGED, "Waiting queue contains an invalid row"
            )
        return PrintervalApiPage(orders=result, raw=payload)

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
        self.login()
        try:
            return self._client.get(FIND_PATH, params=params)
        except httpx.HTTPError as exc:
            raise PrintervalApiError(
                ErrorClass.TRANSIENT_NETWORK, "Waiting queue retry failed", retryable=True
            ) from exc
