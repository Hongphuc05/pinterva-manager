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
