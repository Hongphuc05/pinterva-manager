
import pytest

from app.adapters.db.models import Assignment, Order, Platform, User, WorkflowEvent
from app.application.auth import hash_password
from app.application.order_queries import (
    get_order_detail_for_user,
    get_order_history,
    list_orders_for_user,
)
from app.domain.models import OrderState


def _make_user(db_session, role, username, platform_id=None):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("x"),
        platform_id=platform_id,
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


def test_support_sees_waiting_and_classified_orders_in_own_platform(db_session):
    platform = Platform(name="Support queue platform", account_username="support-queue@example.com")
    other_platform = Platform(name="Other platform", account_username="other@example.com")
    db_session.add_all([platform, other_platform])
    db_session.commit()
    support = _make_user(db_session, "support", "support_queue", platform.id)
    waiting = Order(
        external_order_id="SUPPORT-WAITING",
        platform_id=platform.id,
        state=OrderState.WAITING.value,
    )
    doing = Order(
        external_order_id="SUPPORT-DOING",
        platform_id=platform.id,
        state=OrderState.IN_PROGRESS.value,
    )
    classified_duplicate = Order(
        external_order_id="SUPPORT-DUPLICATE",
        platform_id=platform.id,
        state=OrderState.IN_PROGRESS.value,
        work_domain="duplicate",
        duplicate_check_status="duplicate",
    )
    classified_review = Order(
        external_order_id="SUPPORT-REVIEW",
        platform_id=platform.id,
        state=OrderState.QC_PENDING.value,
        work_domain="standard",
        duplicate_check_status="non_duplicate",
    )
    classified_done = Order(
        external_order_id="SUPPORT-DONE",
        platform_id=platform.id,
        state=OrderState.DONE.value,
        work_domain="standard",
        duplicate_check_status="non_duplicate",
    )
    other_waiting = Order(
        external_order_id="SUPPORT-OTHER-PLATFORM",
        platform_id=other_platform.id,
        state=OrderState.WAITING.value,
    )
    db_session.add_all([waiting, doing, classified_duplicate, classified_review, classified_done, other_waiting])
    db_session.commit()

    visible = list_orders_for_user(db_session, support)

    assert {item.external_order_id for item in visible} == {
        "SUPPORT-WAITING",
        "SUPPORT-DUPLICATE",
        "SUPPORT-REVIEW",
        "SUPPORT-DONE",
    }
    assert get_order_detail_for_user(db_session, support, str(waiting.id)) is waiting
    assert get_order_detail_for_user(db_session, support, str(doing.id)) is None
    assert get_order_detail_for_user(db_session, support, str(classified_duplicate.id)) is classified_duplicate
    assert get_order_detail_for_user(db_session, support, str(classified_review.id)) is classified_review
    assert get_order_detail_for_user(db_session, support, str(classified_done.id)) is classified_done
    assert get_order_detail_for_user(db_session, support, str(other_waiting.id)) is None


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


@pytest.mark.parametrize(
    ("role", "work_domain"),
    [("designer", "standard"), ("designer-trello", "duplicate")],
)
def test_unreleased_fix_is_hidden_from_designers_until_admin_approves(db_session, role, work_domain):
    designer = _make_user(db_session, role, f"unreleased-fix-{role}")
    order = Order(
        external_order_id=f"UNRELEASED-{role}",
        state=OrderState.REVISION.value,
        work_domain=work_domain,
        fix_approved_by_admin=False,
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(Assignment(order_id=order.id, designer_id=designer.id, status="approved"))
    db_session.commit()

    assert list_orders_for_user(db_session, designer) == []
    assert get_order_detail_for_user(db_session, designer, str(order.id)) is None

    order.fix_approved_by_admin = True
    db_session.commit()

    assert [item.id for item in list_orders_for_user(db_session, designer)] == [order.id]
    assert get_order_detail_for_user(db_session, designer, str(order.id)) is order


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
