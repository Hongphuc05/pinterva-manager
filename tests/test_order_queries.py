
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
    admin = _make_user(db_session, "admin", "admin_q1")
    db_session.add(Order(external_order_id="DJ1", state=OrderState.DISCOVERED.value))
    db_session.add(Order(external_order_id="DJ2", state=OrderState.DISCOVERED.value))
    db_session.commit()

    orders = list_orders_for_user(db_session, admin)

    assert {o.external_order_id for o in orders} == {"DJ1", "DJ2"}


def test_list_orders_for_user_designer_only_sees_own_orders(db_session):
    designer = _make_user(db_session, "designer", "designer_q2a")
    other_designer = _make_user(db_session, "designer", "designer_q2b")
    o1 = Order(external_order_id="DJ1", state=OrderState.OPEN.value)
    o2 = Order(external_order_id="DJ2", state=OrderState.OPEN.value)
    db_session.add_all([o1, o2])
    db_session.commit()
    db_session.add(Assignment(order_id=o1.id, designer_id=designer.id, status="approved"))
    db_session.add(Assignment(order_id=o2.id, designer_id=other_designer.id, status="approved"))
    db_session.commit()

    orders = list_orders_for_user(db_session, designer)

    assert {o.external_order_id for o in orders} == {"DJ1"}


def test_list_orders_for_user_designer_with_designer_id_filter(db_session):
    designer = _make_user(db_session, "designer", "designer_q3a")
    other_designer = _make_user(db_session, "designer", "designer_q3b")
    o1 = Order(external_order_id="DJ1", state=OrderState.OPEN.value)
    o2 = Order(external_order_id="DJ2", state=OrderState.OPEN.value)
    db_session.add_all([o1, o2])
    db_session.commit()
    db_session.add(Assignment(order_id=o1.id, designer_id=designer.id, status="approved"))
    db_session.add(Assignment(order_id=o2.id, designer_id=other_designer.id, status="approved"))
    db_session.commit()

    orders = list_orders_for_user(db_session, designer, designer_id=str(designer.id))

    assert [o.external_order_id for o in orders] == ["DJ1"]


def test_get_order_detail_for_user_designer_cannot_view_unassigned_order(db_session):
    designer = _make_user(db_session, "designer", "designer_q4")
    order = Order(external_order_id="DJ1", state=OrderState.OPEN.value)
    db_session.add(order)
    db_session.commit()

    unassigned_result = get_order_detail_for_user(db_session, designer, str(order.id))
    assert unassigned_result is None

    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    assigned_result = get_order_detail_for_user(db_session, designer, str(order.id))
    assert assigned_result is not None
    assert assigned_result.external_order_id == "DJ1"


def test_trello_designer_only_sees_own_duplicate_orders(db_session):
    trello_designer = _make_user(db_session, "designer-trello", "trello_q5a")
    other_trello_designer = _make_user(db_session, "designer-trello", "trello_q5b")
    owned = Order(
        external_order_id="DUP-OWNED",
        state=OrderState.IN_PROGRESS.value,
        work_domain="duplicate",
    )
    another = Order(
        external_order_id="DUP-ANOTHER",
        state=OrderState.IN_PROGRESS.value,
        work_domain="duplicate",
    )
    standard = Order(
        external_order_id="STANDARD-ORDER",
        state=OrderState.IN_PROGRESS.value,
        work_domain="standard",
    )
    db_session.add_all([owned, another, standard])
    db_session.flush()
    db_session.add_all(
        [
            Assignment(order_id=owned.id, designer_id=trello_designer.id, status="approved"),
            Assignment(order_id=another.id, designer_id=other_trello_designer.id, status="approved"),
        ]
    )
    db_session.commit()

    orders = list_orders_for_user(db_session, trello_designer)

    assert [order.external_order_id for order in orders] == ["DUP-OWNED"]
    assert get_order_detail_for_user(db_session, trello_designer, str(owned.id)) is owned
    assert get_order_detail_for_user(db_session, trello_designer, str(another.id)) is None
    assert get_order_detail_for_user(db_session, trello_designer, str(standard.id)) is None


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
