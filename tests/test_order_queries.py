from app.adapters.db.models import Assignment, Order, User, WorkflowEvent
from app.application.auth import hash_password
from app.application.order_queries import (
    get_order_detail_for_user,
    get_order_history,
    list_orders_for_user,
)
from app.domain.models import OrderState


def _make_user(db_session, role, username):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("x"),
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_list_orders_for_user_admin_sees_all(db_session):
    admin = _make_user(db_session, "admin", "admin1")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.add(Order(external_order_id="DJ2", state=OrderState.DISCOVERED.value))
    db_session.commit()

    orders = list_orders_for_user(db_session, admin)

    assert {o.external_order_id for o in orders} == {"DJ1", "DJ2"}


def test_list_orders_for_user_designer_sees_all_platform_orders(db_session):
    designer = _make_user(db_session, "designer", "designer1")
    other_designer = _make_user(db_session, "designer", "designer2")
    o1 = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    o2 = Order(external_order_id="DJ2", state=OrderState.DISCOVERED.value)
    db_session.add_all([o1, o2])
    db_session.commit()
    db_session.add(Assignment(order_id=o1.id, designer_id=designer.id, status="approved"))
    db_session.add(Assignment(order_id=o2.id, designer_id=other_designer.id, status="approved"))
    db_session.commit()

    orders = list_orders_for_user(db_session, designer)

    assert {o.external_order_id for o in orders} == {"DJ1", "DJ2"}


def test_list_orders_for_user_designer_with_designer_id_filter(db_session):
    designer = _make_user(db_session, "designer", "designer1")
    other_designer = _make_user(db_session, "designer", "designer2")
    o1 = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    o2 = Order(external_order_id="DJ2", state=OrderState.DISCOVERED.value)
    db_session.add_all([o1, o2])
    db_session.commit()
    db_session.add(Assignment(order_id=o1.id, designer_id=designer.id, status="approved"))
    db_session.add(Assignment(order_id=o2.id, designer_id=other_designer.id, status="approved"))
    db_session.commit()

    orders = list_orders_for_user(db_session, designer, designer_id=str(designer.id))

    assert [o.external_order_id for o in orders] == ["DJ1"]


def test_get_order_detail_for_user_designer_can_view_any_platform_order(db_session):
    designer = _make_user(db_session, "designer", "designer1")
    order = Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value)
    db_session.add(order)
    db_session.commit()

    result = get_order_detail_for_user(db_session, designer, str(order.id))

    assert result is not None
    assert result.external_order_id == "DJ1"


def test_get_order_detail_for_user_invalid_uuid_returns_none(db_session):
    admin = _make_user(db_session, "admin", "admin1")

    result = get_order_detail_for_user(db_session, admin, "not-a-uuid")

    assert result is None


def test_get_order_history_returns_events_in_order(db_session):
    order = Order(external_order_id="DJ1", state=OrderState.CLAIMED_IMPORTED.value)
    db_session.add(order)
    db_session.commit()
    db_session.add(
        WorkflowEvent(order_id=order.id, from_state="DISCOVERED", to_state="CLAIMED_IMPORTED")
    )
    db_session.commit()

    events = get_order_history(db_session, str(order.id))

    assert len(events) == 1
    assert events[0].to_state == "CLAIMED_IMPORTED"
