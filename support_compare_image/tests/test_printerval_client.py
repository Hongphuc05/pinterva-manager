import httpx
from support_compare_image.config import Settings
from support_compare_image.printerval_client import PrintervalClient


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://user:pass@localhost/db",
        printerval_team_outsource="thuyhuong",
        printerval_session_cookie="full-cookie-value",
    )


def test_client_preserves_api_metadata_and_uses_confirmed_find_params():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        params = dict(request.url.params)
        status = params.get("status")
        if status == "waiting":
            payload = {"status": "successful", "result": []}
        else:
            payload = {
                "status": "successful",
                "meta": {"total_count": 101, "page_count": 2},
                "result": [{"id": 987, "status": "done"}],
            }
        return httpx.Response(200, json=payload, request=request)

    transport = httpx.MockTransport(handler)
    with PrintervalClient(
        _settings(),
        client=httpx.Client(transport=transport, base_url="https://printerval.com"),
    ) as client:
        page = client.fetch_page(status="done", page_id=1, page_size=100)

    assert page.total_count == 101
    assert page.page_count == 2
    assert page.rows == [{"id": 987, "status": "done"}]
    assert len(seen) == 2
    request = seen[-1]
    params = dict(request.url.params)
    assert request.url.path == "/outsource/pod/design-job/find"
    assert params == {
        "page_size": "100",
        "page_id": "1",
        "status": "done",
        "time_type": "created_at",
        "job_type": "all",
        "team_outsource": "thuyhuong",
    }
