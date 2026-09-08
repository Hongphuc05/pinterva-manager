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


def test_discover_waiting_page_sends_date_from_and_date_to_only_when_given():
    seen_params = []

    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": ADMIN_PATH})
        if request.method == "GET" and request.url.path == FIND_PATH:
            seen_params.append(dict(request.url.params))
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        client.discover_waiting_page()
        client.discover_waiting_page(date_from="2026-09-01 00:00:00", date_to="2026-09-07 23:59:59")

    assert "date_from" not in seen_params[0]
    assert "date_to" not in seen_params[0]
    assert seen_params[1]["date_from"] == "2026-09-01 00:00:00"
    assert seen_params[1]["date_to"] == "2026-09-07 23:59:59"


def test_find_order_tries_each_status_until_one_matches():
    """Live-confirmed 2026-09-08: `search=` only matches together with the order's
    exact current status — a mismatched status returns 0 rows, not an error."""
    seen_statuses = []

    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": ADMIN_PATH})
        if request.method == "GET" and request.url.path == FIND_PATH:
            params = dict(request.url.params)
            seen_statuses.append(params["status"])
            assert params["search"] == "DJ3968034"
            if params["status"] == "review":
                return httpx.Response(
                    200, json={"status": "successful", "result": [{"id": 3968034, "status": "review"}]}
                )
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        row = client.find_order("DJ3968034")

    assert row == {"id": 3968034, "status": "review"}
    # "doing" and "waiting" (the two confirmed-common cases) tried first, in that
    # order, before falling through to "review" where it actually matched.
    assert seen_statuses == ["doing", "waiting", "review"]


def test_find_order_normalizes_a_bare_numeric_id_to_the_dj_code():
    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": ADMIN_PATH})
        if request.method == "GET" and request.url.path == FIND_PATH:
            assert dict(request.url.params)["search"] == "DJ3968034"
            return httpx.Response(200, json={"status": "successful", "result": [{"id": 3968034}]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        row = client.find_order("3968034")

    assert row == {"id": 3968034}


def test_find_order_rejects_a_row_whose_id_does_not_match_the_requested_order():
    """Regression test (live incident 2026-09-08): for a status that isn't the order's
    real one, the endpoint was observed to return an unrelated order's row instead of
    zero rows (search silently not applied) — DJ1475396 got overwritten with a
    completely different order's product/deadline/source files as a result. A
    mismatched id must be treated exactly like an empty result, not trusted."""
    seen_statuses = []

    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": ADMIN_PATH})
        if request.method == "GET" and request.url.path == FIND_PATH:
            params = dict(request.url.params)
            seen_statuses.append(params["status"])
            if params["status"] == "doing":
                # Wrong status for this order -> site returns an unrelated row instead
                # of the documented empty result.
                return httpx.Response(
                    200, json={"status": "successful", "result": [{"id": 9999999, "status": "doing"}]}
                )
            if params["status"] == "waiting":
                return httpx.Response(
                    200, json={"status": "successful", "result": [{"id": 1475396, "status": "waiting"}]}
                )
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        row = client.find_order("DJ1475396")

    assert row == {"id": 1475396, "status": "waiting"}
    assert seen_statuses == ["doing", "waiting"]


def test_find_order_returns_none_when_not_found_under_any_status():
    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": ADMIN_PATH})
        if request.method == "GET" and request.url.path == FIND_PATH:
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with _client(handler) as client:
        assert client.find_order("DJ0000001") is None
