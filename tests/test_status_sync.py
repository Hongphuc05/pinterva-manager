import httpx

from app.adapters.db.models import Order, Platform, PlatformSyncState
from app.adapters.printerval.api_client import FIND_PATH, LOGIN_PATH, PrintervalApiClient
from app.application.status_sync import sync_all_platforms, sync_platform_order_statuses


def _mock_client(rows_by_status: dict[str, list[dict]]) -> PrintervalApiClient:
    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if request.method == "GET" and request.url.path == FIND_PATH:
            status = dict(request.url.params)["status"]
            return httpx.Response(
                200, json={"status": "successful", "result": rows_by_status.get(status, [])}
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    return PrintervalApiClient(
        base_url="https://printerval.test",
        username="op@example.test",
        password="pw",
        team_outsource="team-a",
        client=httpx.Client(base_url="https://printerval.test", transport=httpx.MockTransport(handler)),
    )


def test_sync_platform_order_statuses_updates_matching_orders_only(db_session):
    platform = Platform(name="P1", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()

    db_session.add(Order(external_order_id="DJ1001", platform_id=platform.id, state="DISCOVERED"))
    db_session.add(Order(external_order_id="DJ9999", platform_id=platform.id, state="DISCOVERED"))  # not on site
    db_session.commit()

    client = _mock_client({"doing": [{"id": 1001, "status": "doing"}]})
    result = sync_platform_order_statuses(db_session, platform, api_client=client)

    order1 = db_session.query(Order).filter_by(external_order_id="DJ1001").one()
    order2 = db_session.query(Order).filter_by(external_order_id="DJ9999").one()
    assert order1.printerval_status == "doing"
    assert order1.printerval_status_synced_at is not None
    assert order2.printerval_status is None
    assert result["checked"] == 2
    assert result["updated"] == 1


def test_sync_all_platforms_tracks_running_state_and_result(db_session, monkeypatch):
    platform = Platform(
        name="P1",
        account_username="acc1@printerval.com",
        account_password="pw",
        team_outsource="team-a",
        is_active=True,
    )
    db_session.add(platform)
    db_session.flush()
    db_session.add(Order(external_order_id="DJ2002", platform_id=platform.id, state="DISCOVERED"))
    db_session.commit()

    import app.application.status_sync as status_sync_module

    calls = []

    def _fake_sync(session, plat):
        calls.append(plat.id)
        return {"checked": 1, "updated": 0}

    # Patch just the per-platform sync so this test doesn't need network mocking.
    monkeypatch.setattr(status_sync_module, "sync_platform_order_statuses", _fake_sync)
    results = sync_all_platforms(db_session)

    assert calls == [platform.id]
    assert results[str(platform.id)] == {"checked": 1, "updated": 0}

    state = db_session.get(PlatformSyncState, platform.id)
    assert state.is_running is False
    assert state.last_finished_at is not None
    assert state.last_result == {"checked": 1, "updated": 0}
    assert state.last_error is None


def test_sync_all_platforms_skips_platforms_without_credentials(db_session):
    # No account_password and no team_outsource — sync_all_platforms must skip this
    # platform outright rather than attempt a login guaranteed to fail.
    platform = Platform(name="P2", account_username="acc2@printerval.com", is_active=True)
    db_session.add(platform)
    db_session.commit()

    results = sync_all_platforms(db_session)

    assert results == {}
    assert db_session.get(PlatformSyncState, platform.id) is None
