import httpx

from app.adapters.db.models import Order, Platform, PlatformSyncState
from app.adapters.printerval.api_client import FIND_PATH, LOGIN_PATH, PrintervalApiClient
from app.application.status_sync import (
    sync_all_platforms,
    sync_platform_order_statuses,
    sync_selected_order_statuses,
)


def _mock_client(rows_by_code: dict[str, dict]) -> PrintervalApiClient:
    """rows_by_code: {"DJ1001": {"id": 1001, "status": "doing"}} — mirrors the real
    site's search= behavior (only returns a row when both search and status match)."""

    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if request.method == "GET" and request.url.path == FIND_PATH:
            params = dict(request.url.params)
            row = rows_by_code.get(params.get("search"))
            result = [row] if row and row.get("status") == params["status"] else []
            return httpx.Response(200, json={"status": "successful", "result": result})
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

    client = _mock_client(
        {
            "DJ1001": {
                "id": 1001,
                "status": "doing",
                "designer": "Nguyễn Thị Thuý Hường - 2D Prin",
            }
        }
    )
    result = sync_platform_order_statuses(db_session, platform, api_client=client)

    order1 = db_session.query(Order).filter_by(external_order_id="DJ1001").one()
    order2 = db_session.query(Order).filter_by(external_order_id="DJ9999").one()
    assert order1.printerval_status == "doing"
    assert order1.printerval_status_synced_at is not None
    assert order1.printerval_designer == "Nguyễn Thị Thuý Hường - 2D Prin"
    assert order1.printerval_designer_synced_at is not None
    assert order2.printerval_status is None
    # DJ9999 was still looked up (and its sync attempt noted), just not found on site.
    assert order2.printerval_status_synced_at is None
    assert result["checked"] == 2
    assert result["updated"] == 1
    assert result["not_found"] == 1


def test_sync_selected_order_statuses_only_updates_requested_orders(db_session):
    platform = Platform(name="P1", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    selected = Order(
        external_order_id="DJ1001",
        platform_id=platform.id,
        state="IN_PROGRESS",
        printerval_status="doing",
    )
    untouched = Order(
        external_order_id="DJ1002",
        platform_id=platform.id,
        state="IN_PROGRESS",
        printerval_status="doing",
    )
    db_session.add_all([selected, untouched])
    db_session.commit()

    result = sync_selected_order_statuses(
        db_session,
        platform,
        [selected],
        api_client=_mock_client({"DJ1001": {"id": 1001, "status": "done"}}),
    )

    db_session.refresh(selected)
    db_session.refresh(untouched)
    assert result == {"checked": 1, "updated": 1, "not_found": 0, "failed": 0}
    assert selected.state == "DONE"
    assert selected.printerval_status == "done"
    assert untouched.state == "IN_PROGRESS"
    assert untouched.printerval_status == "doing"


def test_sync_platform_order_statuses_tries_the_last_known_status_first(db_session):
    """Regression test for the design this replaced: a live incident paged through
    every one of the 6 statuses in full for one platform (30+ pages of "done" alone)
    before even finishing — cost must scale with our own order count, not the site's
    full history. One find_order call per order, hinted by its last-known status."""
    platform = Platform(name="P1", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    db_session.add(
        Order(
            external_order_id="DJ1001",
            platform_id=platform.id,
            state="DISCOVERED",
            printerval_status="review",
        )
    )
    db_session.commit()

    seen_statuses = []

    def handler(request):
        if request.method == "GET" and request.url.path == LOGIN_PATH:
            return httpx.Response(200, text='<input type="hidden" name="_token" value="csrf">')
        if request.method == "POST" and request.url.path == LOGIN_PATH:
            return httpx.Response(302, headers={"location": "/admin"})
        if request.method == "GET" and request.url.path == FIND_PATH:
            params = dict(request.url.params)
            seen_statuses.append(params["status"])
            if params["status"] == "review":
                return httpx.Response(
                    200, json={"status": "successful", "result": [{"id": 1001, "status": "review"}]}
                )
            return httpx.Response(200, json={"status": "successful", "result": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = PrintervalApiClient(
        base_url="https://printerval.test",
        username="op@example.test",
        password="pw",
        team_outsource="team-a",
        client=httpx.Client(base_url="https://printerval.test", transport=httpx.MockTransport(handler)),
    )
    sync_platform_order_statuses(db_session, platform, api_client=client)

    assert seen_statuses == ["review"]  # matched on the very first (hinted) try


def test_sync_platform_order_statuses_does_not_treat_designer_email_as_assignee(db_session):
    platform = Platform(name="P1", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    order = Order(
        external_order_id="DJ1001",
        platform_id=platform.id,
        state="DISCOVERED",
        # Simulates a value written before designer_email was identified as order
        # metadata rather than the Printerval Designer dropdown selection.
        printerval_designer="fish.311021@gmail.com",
    )
    db_session.add(order)
    db_session.commit()

    client = _mock_client(
        {
            "DJ1001": {
                "id": 1001,
                "status": "waiting",
                "attributes": {"designer_email": "fish.311021@gmail.com"},
            }
        }
    )
    sync_platform_order_statuses(db_session, platform, api_client=client)

    assert order.printerval_designer is None
    assert order.printerval_designer_synced_at is not None


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


def test_sync_all_platforms_continues_past_a_non_printerval_exception(db_session, monkeypatch):
    """Regression test for a live incident: sqlalchemy.orm.exc.StaleDataError (two
    overlapping sync runs racing on the same Order row's optimistic-lock version) was
    not a PrintervalApiError, so it propagated straight out of the per-platform loop
    — silently skipping every platform after the failing one."""
    platform_a = Platform(
        name="A", account_username="a@printerval.com", account_password="pw", team_outsource="team-a"
    )
    platform_b = Platform(
        name="B", account_username="b@printerval.com", account_password="pw", team_outsource="team-b"
    )
    db_session.add_all([platform_a, platform_b])
    db_session.commit()

    import app.application.status_sync as status_sync_module

    calls = []

    def _fake_sync(session, plat):
        calls.append(plat.id)
        if plat.id == platform_a.id:
            raise RuntimeError("simulated StaleDataError-like failure")
        return {"checked": 0, "updated": 0}

    monkeypatch.setattr(status_sync_module, "sync_platform_order_statuses", _fake_sync)
    results = sync_all_platforms(db_session)

    assert calls == [platform_a.id, platform_b.id]  # platform_b still got processed
    assert "simulated StaleDataError-like failure" in results[str(platform_a.id)]["error"]
    assert results[str(platform_b.id)] == {"checked": 0, "updated": 0}
    assert db_session.get(PlatformSyncState, platform_a.id).is_running is False
    assert db_session.get(PlatformSyncState, platform_b.id).is_running is False


def test_sync_all_platforms_skips_platforms_without_credentials(db_session):
    # No account_password and no team_outsource — sync_all_platforms must skip this
    # platform outright rather than attempt a login guaranteed to fail.
    platform = Platform(name="P2", account_username="acc2@printerval.com", is_active=True)
    db_session.add(platform)
    db_session.commit()

    results = sync_all_platforms(db_session)

    assert results == {}


def test_sync_all_platforms_includes_cookie_only_platform(db_session, monkeypatch):
    platform = Platform(
        name="Cookie platform",
        account_username="cookie@printerval.com",
        account_password=None,
        session_cookie="laravel_session=valid-cookie",
        team_outsource="team-cookie",
        is_active=True,
    )
    db_session.add(platform)
    db_session.commit()

    import app.application.status_sync as status_sync_module

    seen = []
    monkeypatch.setattr(
        status_sync_module,
        "sync_platform_order_statuses",
        lambda session, candidate: seen.append(candidate.id) or {"checked": 0, "updated": 0, "not_found": 0},
    )

    results = sync_all_platforms(db_session)

    assert seen == [platform.id]
    assert results[str(platform.id)]["checked"] == 0
    state = db_session.get(PlatformSyncState, platform.id)
    assert state is not None
    assert state.is_running is False


def test_sync_platform_order_statuses_maps_designer_email_to_full_name(db_session):
    platform = Platform(name="P3", account_username="acc3@printerval.com", team_outsource="team-c")
    db_session.add(platform)
    db_session.flush()

    db_session.add(Order(external_order_id="DJ3904000", platform_id=platform.id, state="DISCOVERED"))
    db_session.commit()

    client = _mock_client(
        {
            "DJ3904000": {
                "id": 3904000,
                "status": "doing",
                "attributes": {"designer_email": "thuyhg.22102001@gmail.com"},
            }
        }
    )
    client._designer_map_cache = {"thuyhg.22102001@gmail.com": "Nguyễn Thị Thuý Hường - 2D Prin"}

    sync_platform_order_statuses(db_session, platform, api_client=client)

    order = db_session.query(Order).filter_by(external_order_id="DJ3904000").one()
    assert order.printerval_status == "doing"
    assert order.printerval_designer == "Nguyễn Thị Thuý Hường - 2D Prin"
    assert order.printerval_designer_synced_at is not None
