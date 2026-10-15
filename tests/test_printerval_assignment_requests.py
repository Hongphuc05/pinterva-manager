from app.adapters.db.models import Order, Platform, PrintervalAssignmentRequest, User
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.application.printerval_assignment_requests import create_request, execute_request
from app.domain.models import OrderState


def _platform() -> Platform:
    return Platform(
        name="Mother account",
        account_username="mother@example.com",
        account_password="stored-secret",
        team_outsource="2D",
        printerval_designer_options=["Nguyễn Thị Thuý Hường - 2D Prin"],
    )


def _designer() -> User:
    return User(
        username="internal-designer",
        full_name="Internal Designer",
        role="designer",
        password_hash="hash",
    )


def test_request_updates_designer_and_status_and_mirrors_verified_values(db_session):
    platform = _platform()
    designer = _designer()
    db_session.add_all([platform, designer])
    db_session.flush()
    order = Order(
        external_order_id="DJ0000001",
        platform_id=platform.id,
        state=OrderState.ASSIGNED.value,
    )
    db_session.add(order)
    db_session.commit()
    request = create_request(
        db_session,
        order=order,
        internal_designer=designer,
        platform_id=platform.id,
        designer_option="Nguyễn Thị Thuý Hường - 2D Prin",
        target_status="Doing",
    )
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id=order.external_order_id,
        product_name="Mug",
        designer=None,
        status="Waiting",
    )

    result = execute_request(db_session, adapter, request)

    assert result == {
        "lifecycle": "succeeded",
        "designer": "Nguyễn Thị Thuý Hường - 2D Prin",
        "status": "Doing",
    }
    assert order.printerval_designer == "Nguyễn Thị Thuý Hường - 2D Prin"
    assert order.printerval_status == "doing"
    assert db_session.get(PrintervalAssignmentRequest, request.id).lifecycle == "succeeded"


def test_status_only_request_preserves_designer_and_updates_verified_status(db_session):
    platform = _platform()
    platform.printerval_designer_options = None
    designer = _designer()
    db_session.add_all([platform, designer])
    db_session.flush()
    order = Order(
        external_order_id="DJ000000-status-only",
        platform_id=platform.id,
        printerval_designer="Existing Designer",
    )
    db_session.add(order)
    db_session.commit()
    request = create_request(
        db_session,
        order=order,
        internal_designer=designer,
        platform_id=platform.id,
        designer_option=None,
        target_status="Review",
    )
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id=order.external_order_id,
        product_name="Mug",
        designer="Existing Designer",
        status="Waiting",
    )

    result = execute_request(db_session, adapter, request)

    assert result == {"lifecycle": "succeeded", "designer": None, "status": "Review"}
    assert adapter._orders[order.external_order_id].designer == "Existing Designer"
    assert adapter._orders[order.external_order_id].status == "Review"
    assert order.printerval_designer == "Existing Designer"
    assert order.printerval_status == "review"


def test_request_fails_before_writing_when_designer_is_no_longer_an_option(db_session):
    platform = _platform()
    designer = _designer()
    db_session.add_all([platform, designer])
    db_session.flush()
    order = Order(external_order_id="DJ0000002", platform_id=platform.id)
    db_session.add(order)
    db_session.commit()
    request = create_request(
        db_session,
        order=order,
        internal_designer=designer,
        platform_id=platform.id,
        designer_option="Removed Designer",
        target_status="Doing",
    )
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id=order.external_order_id,
        product_name="Mug",
        designer=None,
        status="Waiting",
    )

    result = execute_request(db_session, adapter, request)

    assert result["lifecycle"] == "failed"
    assert result["error_class"] == "EXTERNAL_CHANGED"
    assert adapter._orders[order.external_order_id].designer is None
    assert adapter._orders[order.external_order_id].status == "Waiting"


def test_request_matches_designer_case_insensitively_and_updates_status_to_doing(db_session):
    platform = _platform()
    designer = _designer()
    db_session.add_all([platform, designer])
    db_session.flush()
    order = Order(
        external_order_id="DJ0000003",
        platform_id=platform.id,
        state=OrderState.ASSIGNED.value,
    )
    db_session.add(order)
    db_session.commit()
    # Lowercase string without dash should fuzzy-match "Nguyễn Thị Thuý Hường - 2D Prin"
    request = create_request(
        db_session,
        order=order,
        internal_designer=designer,
        platform_id=platform.id,
        designer_option="nguyễn thị thúy hường 2d prin",
        target_status="Doing",
    )
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id=order.external_order_id,
        product_name="Mug",
        designer=None,
        status="Waiting",
    )

    result = execute_request(db_session, adapter, request)

    assert result["lifecycle"] == "succeeded"
    assert result["designer"] == "Nguyễn Thị Thuý Hường - 2D Prin"
    assert result["status"] == "Doing"
    assert order.printerval_designer == "Nguyễn Thị Thuý Hường - 2D Prin"
    assert order.printerval_status == "doing"


def test_request_auto_loads_designer_options_if_missing_on_platform(db_session):
    platform = _platform()
    platform.printerval_designer_options = None
    designer = _designer()
    db_session.add_all([platform, designer])
    db_session.flush()
    order = Order(
        external_order_id="DJ0000004",
        platform_id=platform.id,
        state=OrderState.ASSIGNED.value,
    )
    db_session.add(order)
    db_session.commit()

    class _FakeApiClient:
        def list_designer_options(self):
            return ["Nguyễn Thị Thuý Hường - 2D Prin"]

    adapter = FakePrintervalAdapter()
    adapter.api_client = _FakeApiClient()
    adapter.add_order(
        external_order_id=order.external_order_id,
        product_name="Mug",
        designer=None,
        status="Waiting",
    )

    request = create_request(
        db_session,
        order=order,
        internal_designer=designer,
        platform_id=platform.id,
        designer_option="nguyễn thị thúy hường 2d prin",
        target_status="Doing",
    )

    result = execute_request(db_session, adapter, request)

    assert result["lifecycle"] == "succeeded"
    assert result["status"] == "Doing"
    assert platform.printerval_designer_options == ["Nguyễn Thị Thuý Hường - 2D Prin"]


def test_a_failed_designer_step_is_reported_not_hidden(db_session):
    from app.adapters.printerval.models import WriteResult

    platform = _platform()
    designer = _designer()
    db_session.add_all([platform, designer])
    db_session.flush()
    order = Order(external_order_id="DJ0000099", platform_id=platform.id, state=OrderState.ASSIGNED.value)
    db_session.add(order)
    db_session.commit()
    request = create_request(
        db_session, order=order, internal_designer=designer, platform_id=platform.id,
        designer_option="Nguyễn Thị Thuý Hường - 2D Prin", target_status="Doing",
    )
    adapter = FakePrintervalAdapter()
    adapter.add_order(external_order_id="DJ0000099", product_name="x", designer=None, status="waiting")
    adapter.set_designer = lambda *_a, **_k: WriteResult(
        success=False, external_order_id="DJ0000099", error_class="AUTH"
    )

    execute_request(db_session, adapter, request)

    db_session.refresh(request)
    assert request.lifecycle == "failed"  # used to be "succeeded" with no Designer on Printerval
    assert request.error_class == "AUTH"
    assert "Không gán được Designer" in request.error_message
    assert request.observed_status  # the status still went through and is mirrored
    db_session.refresh(order)
    assert (order.printerval_status or "").lower() == "doing"



def _bump_version_elsewhere(db_session, order_id):
    """What a concurrent status sync does: save the same order from another connection."""
    from sqlalchemy import text

    with db_session.get_bind().begin() as conn:
        conn.execute(text("UPDATE orders SET version = version + 1, product_name = 'changed by sync' WHERE id = :id"),
                     {"id": order_id})


def test_a_status_sync_saving_the_order_meanwhile_no_longer_breaks_the_request(db_session):
    platform = _platform()
    designer = _designer()
    db_session.add_all([platform, designer])
    db_session.flush()
    order = Order(external_order_id="DJ0000077", platform_id=platform.id, state=OrderState.ASSIGNED.value)
    db_session.add(order)
    db_session.commit()
    request = create_request(
        db_session, order=order, internal_designer=designer, platform_id=platform.id,
        designer_option="Nguyễn Thị Thuý Hường - 2D Prin", target_status="Doing",
    )
    adapter = FakePrintervalAdapter()
    adapter.add_order(external_order_id="DJ0000077", product_name="x", designer=None, status="waiting")
    real_set_status = adapter.set_status

    def slow_set_status(code, status):
        result = real_set_status(code, status)
        _bump_version_elsewhere(db_session, order.id)  # the sync saved the order while Printerval answered
        return result

    adapter.set_status = slow_set_status

    execute_request(db_session, adapter, request)  # used to raise StaleDataError

    db_session.refresh(request)
    db_session.refresh(order)
    assert request.lifecycle == "succeeded"
    assert (order.printerval_status or "").lower() == "doing"
    assert order.product_name == "changed by sync"  # the sync's own change is kept, not overwritten


def test_requests_stuck_pending_are_ended_as_failed_and_shown_to_admin(db_session):
    from datetime import UTC, datetime, timedelta

    from app.adapters.db.models import DeadLetter
    from app.application.printerval_assignment_requests import fail_stuck_requests

    platform = _platform()
    designer = _designer()
    db_session.add_all([platform, designer])
    db_session.flush()
    old_order = Order(external_order_id="DJ0000066", platform_id=platform.id, state=OrderState.ASSIGNED.value)
    new_order = Order(external_order_id="DJ0000067", platform_id=platform.id, state=OrderState.ASSIGNED.value)
    db_session.add_all([old_order, new_order])
    db_session.commit()
    stuck = create_request(db_session, order=old_order, internal_designer=designer, platform_id=platform.id,
                           designer_option="Nguyễn Thị Thuý Hường - 2D Prin", target_status="Doing")
    fresh = create_request(db_session, order=new_order, internal_designer=designer, platform_id=platform.id,
                           designer_option="Nguyễn Thị Thuý Hường - 2D Prin", target_status="Doing")
    stuck.created_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.commit()

    assert fail_stuck_requests(db_session) == 1

    db_session.refresh(stuck)
    db_session.refresh(fresh)
    assert stuck.lifecycle == "failed" and stuck.error_class == "UNKNOWN_OUTCOME"
    assert fresh.lifecycle == "pending"  # still within its normal run time
    alert = db_session.query(DeadLetter).filter_by(source="printerval.write_failed").one()
    assert alert.payload["order_code"] == "DJ0000066"
