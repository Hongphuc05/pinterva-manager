import json

import httpx
import pytest

from app.adapters.errors import ErrorClass
from app.adapters.printerval.api_client import (
    ADMIN_PATH,
    FIND_PATH,
    LOGIN_PATH,
    PrintervalApiClient,
    PrintervalApiConfigurationError,
    PrintervalApiError,
)


def _client(handler, **overrides):
    options = {
        "base_url": "https://printerval.test",
        "username": "operator@example.test",
        "password": "not-a-real-password",
        "team_outsource": "team-a",
        "client": httpx.Client(
            base_url="https://printerval.test", transport=httpx.MockTransport(handler)
        ),
    }
    options.update(overrides)
    return PrintervalApiClient(**options)


def test_discover_waiting_logs_in_and_uses_read_only_filter():
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(
                200,
                text=(
                    '<form><input type="hidden" name="_token" value="csrf-123">'
                    '<input type="hidden" name="redirect" '
                    'value="/central/outsource/pod/design-job/admin"></form>'
                ),
            )
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            form = dict(item.split("=", 1) for item in request.content.decode().split("&"))
            assert form["_token"] == "csrf-123"
            assert form["redirect"] == ADMIN_PATH.replace("/", "%2F")
            return httpx.Response(302, headers={"location": ADMIN_PATH})
        if request.method == "GET" and request.url.path == FIND_PATH:
            assert dict(request.url.params) == {
                "page_size": "40",
                "page_id": "0",
                "status": "waiting",
                "time_type": "created_at",
                "job_type": "all",
                "team_outsource": "team-a",
            }
            return httpx.Response(200, json={"status": "successful", "result": [{"code": "DJ42"}]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        page = client.discover_waiting_page()

    assert page.orders == [{"code": "DJ42"}]
    assert [(request.method, request.url.path) for request in calls] == [
        ("GET", LOGIN_PATH),
        ("POST", LOGIN_PATH),
        ("GET", FIND_PATH),
    ]


def test_discover_waiting_requires_the_server_side_team_scope_before_network_io():
    with _client(
        lambda request: pytest.fail("network must not be called"), team_outsource=None
    ) as client:
        with pytest.raises(PrintervalApiConfigurationError, match="PRINTERVAL_TEAM_OUTSOURCE"):
            client.discover_waiting_page()


def test_discover_waiting_reauthenticates_once_after_an_expired_session():
    find_calls = 0

    def handler(request):
        nonlocal find_calls
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": ADMIN_PATH})
        if request.method == "GET" and request.url.path == FIND_PATH:
            find_calls += 1
            if find_calls == 1:
                return httpx.Response(401)
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        assert client.discover_waiting_page().orders == []
    assert find_calls == 2


def test_discover_waiting_rejects_an_unknown_schema():
    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": ADMIN_PATH})
        if request.method == "GET" and request.url.path == FIND_PATH:
            return httpx.Response(200, content=json.dumps({"status": "successful", "result": {}}))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        with pytest.raises(PrintervalApiError) as caught:
            client.discover_waiting_page()
    assert caught.value.error_class is ErrorClass.EXTERNAL_CHANGED
