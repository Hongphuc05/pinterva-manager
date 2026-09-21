from datetime import UTC, datetime

import httpx

import app.application.status_sync as status_sync_module
from app.adapters.db.models import Order, Platform, PlatformSyncState, WorkflowEvent
from app.adapters.printerval.api_client import FIND_PATH, LOGIN_PATH, PrintervalApiClient
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.application.status_sync import (
    ACTIVE_PRINTERVAL_STATUS_FILTERS,
    reconcile_active_platform_orders,
    sync_all_platforms,
    sync_full_database_platform_orders,
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
    assert order2.printerval_status == "cancelled"
    # DJ9999 was still looked up (and its sync attempt noted), just not found on site.
    assert order2.printerval_status_synced_at is not None
    assert result["checked"] == 2
    assert result["updated"] == 2
    assert result["not_found"] == 1


def test_platform_sync_does_not_overwrite_tacahu_deadline(db_session):
    platform = Platform(name="P deadline", account_username="acc@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    deadline_tacahu = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    order = Order(
        external_order_id="DJ-DEADLINE-KEEP",
        platform_id=platform.id,
        deadline_tacahu=deadline_tacahu,
    )
    db_session.add(order)
    db_session.commit()

    sync_platform_order_statuses(
        db_session,
        platform,
        api_client=_mock_client({"DJ-DEADLINE-KEEP": {"id": 1, "status": "doing"}}),
    )

    db_session.refresh(order)
    assert order.deadline_tacahu == deadline_tacahu


def test_selected_sync_keeps_review_internal_until_admin_marks_payment(db_session):
    platform = Platform(name="P1", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    selected = Order(
        external_order_id="DJ1001",
        platform_id=platform.id,
        state="QC_PENDING",
        printerval_status="review",
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
    assert selected.state == "QC_PENDING"
    assert selected.printerval_status == "done"
    assert untouched.state == "IN_PROGRESS"
    assert untouched.printerval_status == "doing"


def test_scheduled_sync_keeps_review_internal_when_printerval_reports_done(db_session):
    platform = Platform(name="P review done", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    order = Order(
        external_order_id="DJ1004",
        platform_id=platform.id,
        state="QC_PENDING",
        printerval_status="review",
    )
    db_session.add(order)
    db_session.commit()

    result = sync_platform_order_statuses(
        db_session,
        platform,
        api_client=_mock_client({"DJ1004": {"id": 1004, "status": "done"}}),
    )

    db_session.refresh(order)
    assert result["updated"] == 1
    assert order.state == "QC_PENDING"
    assert order.printerval_status == "done"


def test_scheduled_sync_returns_a_paid_done_order_to_fix_without_clearing_payment(db_session):
    platform = Platform(name="P paid fix", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    order = Order(
        external_order_id="DJ1005",
        platform_id=platform.id,
        state="DONE",
        printerval_status="done",
        is_paid=True,
        paid_at=datetime.now(UTC),
    )
    db_session.add(order)
    db_session.commit()

    result = sync_platform_order_statuses(
        db_session,
        platform,
        api_client=_mock_client({"DJ1005": {"id": 1005, "status": "fix", "note": "Sửa lại logo"}}),
    )

    db_session.refresh(order)
    assert result["updated"] == 1
    assert order.state == "REVISION"
    assert order.is_paid is True
    assert order.fix_return_count == 1


def test_active_reconciliation_skips_untracked_doing_and_fix_without_reading_waiting(db_session):
    platform = Platform(name="P active", account_username="acc@example.test", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    adapter = FakePrintervalAdapter()
    adapter.add_order(external_order_id="DJ-WAIT", product_name="Manual crawl only", designer=None, status="waiting")
    adapter.add_order(external_order_id="DJ-DOING", product_name="Old Doing", designer="Print Des", status="doing")
    adapter.add_order(external_order_id="DJ-FIX", product_name="Old Fix", designer="Print Des", status="fix")

    result = reconcile_active_platform_orders(db_session, platform, adapter=adapter)

    assert db_session.query(Order).filter_by(external_order_id="DJ-WAIT").one_or_none() is None
    assert db_session.query(Order).filter_by(external_order_id="DJ-DOING").one_or_none() is None
    assert db_session.query(Order).filter_by(external_order_id="DJ-FIX").one_or_none() is None
    assert result == {"checked": 2, "added": 0, "updated": 0, "skipped_untracked": 2, "failed": 0}


def test_active_reconciliation_returns_paid_done_order_to_fix(db_session, monkeypatch):
    monkeypatch.setattr(status_sync_module, "_dispatch_admin_fix_notifications", lambda *_: None)
    platform = Platform(name="P active paid", account_username="acc@example.test", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    order = Order(
        external_order_id="DJ-PAID-FIX",
        platform_id=platform.id,
        state="DONE",
        printerval_status="done",
        is_paid=True,
    )
    db_session.add(order)
    db_session.commit()
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id="DJ-PAID-FIX",
        product_name="Paid Fix",
        designer="Print Des",
        status="fix",
        note_outsource="Sửa lại logo",
    )

    result = reconcile_active_platform_orders(db_session, platform, adapter=adapter)

    db_session.refresh(order)
    assert result == {"checked": 1, "added": 0, "updated": 1, "skipped_untracked": 0, "failed": 0}
    assert order.state == "REVISION"
    assert order.printerval_status == "fix"
    assert order.is_paid is True
    assert order.fix_return_count == 1


def test_active_reconciliation_uses_independent_doing_and_fix_filters(db_session):
    platform = Platform(name="P filter", account_username="acc@example.test", team_outsource="team-a")
    db_session.add(platform)
    db_session.commit()

    class RecordingAdapter(FakePrintervalAdapter):
        def __init__(self):
            super().__init__()
            self.status_filters: list[str] = []

        def discover_orders(self, *, status, **kwargs):
            self.status_filters.append(status)
            return super().discover_orders(status=status, **kwargs)

    adapter = RecordingAdapter()
    reconcile_active_platform_orders(db_session, platform, adapter=adapter)
    assert adapter.status_filters == list(ACTIVE_PRINTERVAL_STATUS_FILTERS)


def test_selected_sync_with_unchanged_observation_keeps_order_version(db_session):
    platform = Platform(name="P unchanged", account_username="acc@example.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    order = Order(
        external_order_id="DJ1",
        platform_id=platform.id,
        state="IN_PROGRESS",
        printerval_status="doing",
    )
    db_session.add(order)
    db_session.commit()
    version_before_sync = order.version

    result = sync_selected_order_statuses(
        db_session,
        platform,
        [order],
        api_client=_mock_client({"DJ1": {"id": 1, "status": "doing"}}),
    )

    db_session.refresh(order)
    assert result == {"checked": 1, "updated": 0, "not_found": 0, "failed": 0}
    assert order.version == version_before_sync
    assert order.printerval_status_synced_at is None


def test_selected_sync_turns_printerval_fix_into_the_existing_admin_fix_flow(db_session, monkeypatch):
    notifications = []
    monkeypatch.setattr(
        status_sync_module,
        "_dispatch_admin_fix_notifications",
        lambda _session, order: notifications.append(order.id),
    )
    platform = Platform(name="P1", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    order = Order(
        external_order_id="DJ1003",
        platform_id=platform.id,
        work_domain="duplicate",
        state="IN_PROGRESS",
        printerval_status="doing",
        note_outsource="Ghi chú cũ",
    )
    db_session.add(order)
    db_session.commit()

    result = sync_selected_order_statuses(
        db_session,
        platform,
        [order],
        api_client=_mock_client({
            "DJ1003": {"id": 1003, "status": "fix", "note": "Sửa lại phần tay áo"}
        }),
    )

    db_session.refresh(order)
    event = db_session.query(WorkflowEvent).filter_by(order_id=order.id).one()
    assert result == {"checked": 1, "updated": 1, "not_found": 0, "failed": 0}
    assert order.state == "REVISION"
    assert order.printerval_status == "fix"
    assert order.previous_note_outsource == "Ghi chú cũ"
    assert order.note_outsource == "Sửa lại phần tay áo"
    assert order.fix_approved_by_admin is False
    assert order.fix_return_count == 1
    assert event.evidence["action"] == "REQUEST_FIX"
    assert notifications == [order.id]

    # Re-reading the same Fix state is not another return from Printerval.
    sync_selected_order_statuses(
        db_session,
        platform,
        [order],
        api_client=_mock_client({
            "DJ1003": {"id": 1003, "status": "fix", "note": "Sửa lại phần tay áo"}
        }),
    )
    db_session.refresh(order)
    assert order.fix_return_count == 1
    assert notifications == [order.id]


def test_scheduled_sync_dispatches_admin_telegram_notification_for_new_fix(db_session, monkeypatch):
    notifications = []
    monkeypatch.setattr(
        status_sync_module,
        "_dispatch_admin_fix_notifications",
        lambda _session, order: notifications.append(order.id),
    )
    platform = Platform(name="P1", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    order = Order(
        external_order_id="DJ1006",
        platform_id=platform.id,
        state="IN_PROGRESS",
        printerval_status="doing",
    )
    db_session.add(order)
    db_session.commit()

    result = sync_platform_order_statuses(
        db_session,
        platform,
        api_client=_mock_client({
            "DJ1006": {"id": 1006, "status": "fix", "note": "Sửa lại mockup"}
        }),
    )

    db_session.refresh(order)
    assert result["updated"] == 1
    assert order.state == "REVISION"
    assert order.fix_return_count == 1
    assert notifications == [order.id]


def test_selected_sync_reconciles_a_legacy_rejected_fix_when_printerval_is_review(db_session):
    platform = Platform(name="P1", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    order = Order(
        external_order_id="DJ1004",
        platform_id=platform.id,
        state="REVISION",
        printerval_status="review",
        fix_rejected_by_admin=True,
    )
    db_session.add(order)
    db_session.commit()

    result = sync_selected_order_statuses(
        db_session,
        platform,
        [order],
        api_client=_mock_client({"DJ1004": {"id": 1004, "status": "review"}}),
    )

    db_session.refresh(order)
    assert result == {"checked": 1, "updated": 1, "not_found": 0, "failed": 0}
    assert order.state == "QC_PENDING"


def test_scheduled_sync_reconciles_a_legacy_rejected_fix_when_printerval_is_review(db_session):
    platform = Platform(name="P1", account_username="acc1@printerval.com", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    order = Order(
        external_order_id="DJ1005",
        platform_id=platform.id,
        state="REVISION",
        printerval_status="review",
        fix_rejected_by_admin=True,
    )
    db_session.add(order)
    db_session.commit()

    result = sync_platform_order_statuses(
        db_session,
        platform,
        api_client=_mock_client({"DJ1005": {"id": 1005, "status": "review"}}),
    )

    db_session.refresh(order)
    assert result["updated"] == 1
    assert order.state == "QC_PENDING"


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

    def _fake_sync(session, plat, *, adapter, actor_id=None):
        calls.append(plat.id)
        return {"checked": 1, "updated": 0}

    # Patch just the active-feed reconciler so this test doesn't need network mocking.
    monkeypatch.setattr(status_sync_module, "reconcile_active_platform_orders", _fake_sync)
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

    def _fake_sync(session, plat, *, adapter, actor_id=None):
        calls.append(plat.id)
        if plat.id == platform_a.id:
            raise RuntimeError("simulated StaleDataError-like failure")
        return {"checked": 0, "updated": 0}

    monkeypatch.setattr(status_sync_module, "reconcile_active_platform_orders", _fake_sync)
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
        "reconcile_active_platform_orders",
        lambda session, candidate, *, adapter, actor_id=None: seen.append(candidate.id) or {"checked": 0, "updated": 0},
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


def test_full_database_sync_checks_every_tracked_platform_order(db_session):
    platform = Platform(name="Full sweep", account_username="acc@example.test", team_outsource="team-a")
    db_session.add(platform)
    db_session.flush()
    review = Order(
        external_order_id="DJ3999001",
        platform_id=platform.id,
        state="QC_PENDING",
        printerval_status="review",
    )
    paid_done = Order(
        external_order_id="DJ3999002",
        platform_id=platform.id,
        state="DONE",
        is_paid=True,
        printerval_status="done",
    )
    other_platform = Platform(name="Other", account_username="other@example.test", team_outsource="team-b")
    db_session.add_all([review, paid_done, other_platform])
    db_session.flush()
    db_session.add(
        Order(
            external_order_id="DJ3999003",
            platform_id=other_platform.id,
            state="IN_PROGRESS",
            printerval_status="doing",
        )
    )
    db_session.commit()

    result = sync_full_database_platform_orders(
        db_session,
        platform,
        api_client=_mock_client(
            {
                "DJ3999001": {"id": 3999001, "status": "done"},
                "DJ3999002": {"id": 3999002, "status": "fix"},
            }
        ),
    )

    db_session.refresh(review)
    db_session.refresh(paid_done)
    assert result == {"checked": 2, "updated": 2, "not_found": 0, "failed": 0}
    # Print Done does not bypass the Admin payment decision.
    assert review.state == "QC_PENDING"
    # A paid Done card still returns to Fix when Printerval explicitly requests it.
    assert paid_done.state == "REVISION"
    assert paid_done.is_paid is True
