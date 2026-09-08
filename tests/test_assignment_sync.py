from app.adapters.db.models import DeadLetter, ExternalObservation, Order, User
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.application.assignment_sync import sync_assignment_to_printerval
from app.domain.models import OrderState


def _designer(printerval_option: str | None = "Linh Designer - 2D Prin") -> User:
    return User(
        username="linh",
        full_name="Linh Designer",
        role="designer",
        password_hash="hash",
        printerval_designer_option=printerval_option,
    )


def test_sync_skips_designers_with_no_printerval_registration(db_session):
    adapter = FakePrintervalAdapter()
    order = Order(external_order_id="DJ0000001", state=OrderState.ASSIGNED.value)
    designer = _designer(printerval_option=None)
    db_session.add_all([order, designer])
    db_session.commit()

    result = sync_assignment_to_printerval(db_session, adapter, order, designer)

    assert result == {"synced": False, "reason": "designer_not_registered_on_printerval"}
    assert db_session.query(DeadLetter).count() == 0


def test_sync_sets_designer_then_status_and_records_observations(db_session):
    adapter = FakePrintervalAdapter()
    adapter.add_order(external_order_id="DJ0000001", product_name="Mug", designer=None, status="Waiting")
    order = Order(external_order_id="DJ0000001", state=OrderState.ASSIGNED.value)
    designer = _designer()
    db_session.add_all([order, designer])
    db_session.commit()

    result = sync_assignment_to_printerval(db_session, adapter, order, designer)

    assert result == {"synced": True}
    fake_order = adapter._orders["DJ0000001"]
    assert fake_order.designer == "Linh Designer - 2D Prin"
    assert fake_order.status == "Doing"
    # Our own state machine is untouched — this sync is one-directional to the site.
    assert order.state == OrderState.ASSIGNED.value
    observations = db_session.query(ExternalObservation).filter_by(order_id=order.id).all()
    assert len(observations) == 2
    assert {o.observed_state for o in observations} == {"Linh Designer - 2D Prin", "Doing"}


def test_sync_dead_letters_and_stops_when_set_designer_fails(db_session):
    adapter = FakePrintervalAdapter()
    # DJ0000001 not added to the fake adapter -> set_designer fails VALIDATION.
    order = Order(external_order_id="DJ0000001", state=OrderState.ASSIGNED.value)
    designer = _designer()
    db_session.add_all([order, designer])
    db_session.commit()

    result = sync_assignment_to_printerval(db_session, adapter, order, designer)

    assert result == {"synced": False, "stage": "set_designer"}
    dead_letter = db_session.query(DeadLetter).one()
    assert dead_letter.source == "assignment_sync.set_designer"
    assert dead_letter.payload["order_id"] == "DJ0000001"
    assert db_session.query(ExternalObservation).count() == 0


def test_sync_dead_letters_when_set_status_fails_after_designer_succeeds(db_session, monkeypatch):
    adapter = FakePrintervalAdapter()
    adapter.add_order(external_order_id="DJ0000001", product_name="Mug", designer=None, status="Waiting")
    order = Order(external_order_id="DJ0000001", state=OrderState.ASSIGNED.value)
    designer = _designer()
    db_session.add_all([order, designer])
    db_session.commit()

    from app.adapters.printerval.models import WriteResult

    def _fail_status(external_order_id, target_status):
        return WriteResult(success=False, external_order_id=external_order_id, error_class="VALIDATION")

    monkeypatch.setattr(adapter, "set_status", _fail_status)

    result = sync_assignment_to_printerval(db_session, adapter, order, designer)

    assert result == {"synced": False, "stage": "set_status"}
    # The designer write already succeeded and must not be lost/rolled back.
    assert adapter._orders["DJ0000001"].designer == "Linh Designer - 2D Prin"
    observations = db_session.query(ExternalObservation).filter_by(order_id=order.id).all()
    assert len(observations) == 1
    dead_letter = db_session.query(DeadLetter).one()
    assert dead_letter.source == "assignment_sync.set_status"


def test_sync_is_idempotent_for_the_same_order_and_designer(db_session):
    adapter = FakePrintervalAdapter()
    adapter.add_order(external_order_id="DJ0000001", product_name="Mug", designer=None, status="Waiting")
    order = Order(external_order_id="DJ0000001", state=OrderState.ASSIGNED.value)
    designer = _designer()
    db_session.add_all([order, designer])
    db_session.commit()

    result1 = sync_assignment_to_printerval(db_session, adapter, order, designer)
    result2 = sync_assignment_to_printerval(db_session, adapter, order, designer)

    assert result1 == result2 == {"synced": True}
    # Only one pair of observations was ever written — the second call replayed the
    # cached operation result instead of re-doing the writes.
    assert db_session.query(ExternalObservation).filter_by(order_id=order.id).count() == 2
