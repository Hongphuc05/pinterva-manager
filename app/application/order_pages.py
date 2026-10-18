"""Server-side tab/filter/sort/pagination of the order list, for every role that has one.

Mirrors what OrdersListPage used to do in the browser over the full order list, so a user loads
one page (<=100 orders) instead of every order they can see.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Query, Session

from app.adapters.db.models import Assignment, Order, User
from app.application.order_queries import visible_orders_query
from app.domain.access import ROLE_ADMIN, ROLE_SUPPORT

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

TAB_STATES: dict[str, tuple[str, ...]] = {
    "waiting": ("WAITING", "OPEN_FOR_ALLOCATION", "DISCOVERED", "PENDING", "OPEN"),
    "doing": ("IN_PROGRESS", "DOING", "ASSIGNED"),
    "review": ("QC_PENDING", "RESULT_SUBMITTED", "SUBMITTING_TO_SITE", "REVIEW"),
    "fix": ("REVISION", "REVISION_REQUESTED", "FIX"),
    "done": ("DONE", "CLAIMED_IMPORTED", "COMPLETED", "SKIPPED"),
}
DESIGNER_TABS = ("doing", "fix", "review", "waiting_update", "paid", "done")
SUPPORT_TABS = ("all", "duplicate", "non_duplicate", "doing")
DATE_FIELDS = ("status_changed_at", "order_created_at_ext", "created_at", "deadline_tacahu")
MAX_PAGE_SIZE = 200
MAX_IDS = 5000


def tabs_for_role(role: str) -> tuple[str, ...]:
    if role == ROLE_ADMIN:
        return tuple(TAB_STATES)
    if role == ROLE_SUPPORT:
        return SUPPORT_TABS
    return DESIGNER_TABS


@dataclass
class PageParams:
    role: str = ROLE_ADMIN
    tab: str = "waiting"
    doing_sub: str = "all"  # all | missing | normal
    fix_sub: str = "all"  # all | pending | approved | rejected
    q: str = ""
    status: str | None = None
    designer_id: str | None = None
    platform_status: str | None = None
    batch: str | None = None
    date_field: str = "status_changed_at"
    date_from: date | None = None
    date_to: date | None = None
    fix_returned: bool = False
    synced_images: bool = False
    # Duplicate check: "unchecked" = still tagged Chưa kiểm tra, "checked" = the tag is gone (in
    # Waiting that means Không trùng lặp: duplicates have moved to the board).
    check_status: str | None = None
    sort_field: str = "status_changed_at"
    sort_desc: bool = True
    page: int = 1
    page_size: int = 100


def _upper_state():
    return func.upper(Order.state)


def _designer_tab_condition(tab: str):
    upper = _upper_state()
    not_missing = Order.template_missing.is_(False)
    not_paid = Order.is_paid.is_(False)
    released_fix = and_(
        not_missing, Order.fix_approved_by_admin.is_(True), upper.in_(TAB_STATES["fix"])
    )
    return {
        "doing": and_(not_missing, not_paid, upper.in_(TAB_STATES["doing"])),
        "fix": released_fix,
        "review": and_(not_missing, not_paid, upper.in_(TAB_STATES["review"])),
        "waiting_update": and_(
            or_(Order.template_missing.is_(True), upper == "WAITING_UPDATE"), not_paid
        ),
        "paid": and_(Order.is_paid.is_(True), ~released_fix),
        "done": and_(not_paid, upper.in_(TAB_STATES["done"])),
    }[tab]


def _support_tab_condition(tab: str):
    """Every order Support sees is in exactly one tab; a tag wins over the state."""
    is_duplicate = or_(
        Order.work_domain == "duplicate", Order.duplicate_check_status == "duplicate"
    )
    is_non_duplicate = and_(~is_duplicate, Order.duplicate_check_status == "non_duplicate")
    in_doing = or_(
        _upper_state().in_(("IN_PROGRESS", "ASSIGNED")),
        func.upper(func.coalesce(Order.printerval_status, "")) == "DOING",
    )
    untagged = and_(~is_duplicate, ~is_non_duplicate)
    return {
        "duplicate": is_duplicate,
        "non_duplicate": is_non_duplicate,
        "doing": and_(untagged, in_doing),
        "all": and_(untagged, ~in_doing),
    }[tab]


def tab_condition(role: str, tab: str, doing_sub: str = "all", fix_sub: str = "all"):
    if role == ROLE_ADMIN:
        return _tab_condition(tab, doing_sub, fix_sub)
    if role == ROLE_SUPPORT:
        return _support_tab_condition(tab)
    return _designer_tab_condition(tab)


def _tab_condition(tab: str, doing_sub: str = "all", fix_sub: str = "all"):
    cond = _upper_state().in_(TAB_STATES[tab])
    if tab == "doing" and doing_sub == "missing":
        cond = and_(cond, Order.template_missing.is_(True))
    elif tab == "doing" and doing_sub == "normal":
        cond = and_(cond, Order.template_missing.is_(False))
    elif tab == "fix":
        approved = Order.fix_approved_by_admin.is_(True)
        rejected = Order.fix_rejected_by_admin.is_(True)
        if fix_sub == "pending":
            cond = and_(cond, ~approved, ~rejected)
        elif fix_sub == "approved":
            cond = and_(cond, approved)
        elif fix_sub == "rejected":
            cond = and_(cond, rejected)
    return cond


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
    return f"%{escaped}%"


def _search_condition(q: str, role: str = ROLE_ADMIN):
    pattern = _like(q.strip())
    if role != ROLE_ADMIN:
        # Support also finds an order by its code; a designer never sees the code, so never matches it.
        conds = [Order.product_name.ilike(pattern)]
        if role == ROLE_SUPPORT:
            conds.append(Order.external_order_id.ilike(pattern))
        return or_(*conds)
    designer_names = (
        select(User.id).where(or_(User.full_name.ilike(pattern), User.username.ilike(pattern)))
    )
    assigned_orders = select(Assignment.order_id).where(
        Assignment.status == "approved", Assignment.designer_id.in_(designer_names)
    )
    return or_(
        Order.external_order_id.ilike(pattern),
        Order.product_name.ilike(pattern),
        Order.printerval_designer.ilike(pattern),
        Order.id.in_(assigned_orders),
    )


def _date_expr(field: str):
    if field == "status_changed_at":
        return func.coalesce(Order.status_changed_at, Order.created_at)
    return getattr(Order, field)


def _day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=VN_TZ)


def _apply_filters(query: Query, p: PageParams) -> Query:
    if p.q.strip():
        query = query.filter(_search_condition(p.q, p.role))
    if p.platform_status:
        wanted = p.platform_status.strip().lower()
        if wanted == "unspecified":
            query = query.filter(or_(Order.printerval_status.is_(None), Order.printerval_status == ""))
        else:
            query = query.filter(func.lower(func.trim(Order.printerval_status)) == wanted)
    if p.batch and p.batch.strip() and p.role in (ROLE_ADMIN, ROLE_SUPPORT):
        text = p.batch.strip()
        conds = [Order.external_order_id.ilike(_like(text))]
        try:
            conds.append(Order.batch_id == uuid.UUID(text))
        except ValueError:
            pass
        query = query.filter(or_(*conds))
    if p.date_from or p.date_to:
        expr = _date_expr(p.date_field)
        query = query.filter(expr.is_not(None))
        if p.date_from:
            query = query.filter(expr >= _day_start(p.date_from))
        if p.date_to:
            query = query.filter(expr < _day_start(p.date_to + timedelta(days=1)))
    if p.fix_returned:
        query = query.filter(Order.fix_return_count > 0)
    if p.synced_images:
        query = query.filter(func.coalesce(func.jsonb_array_length(Order.product_image_urls), 0) > 1)
    if p.check_status == "unchecked":
        query = query.filter(or_(Order.duplicate_check_status.is_(None), Order.duplicate_check_status == "uncheck"))
    elif p.check_status == "checked":
        query = query.filter(Order.duplicate_check_status.in_(("duplicate", "non_duplicate")))
    return query


def _count_by_tab(query: Query, role: str) -> dict[str, int]:
    tabs = tabs_for_role(role)
    columns = [func.count(Order.id).filter(tab_condition(role, tab)) for tab in tabs]
    row = query.with_entities(*columns).one()
    return {tab: int(row[i] or 0) for i, tab in enumerate(tabs)}


def summary_counts(base: Query) -> dict:
    """Unfiltered per-tab counters (the numbers on the tab buttons)."""
    upper = _upper_state()
    doing = upper.in_(TAB_STATES["doing"])
    fix = upper.in_(TAB_STATES["fix"])
    approved = Order.fix_approved_by_admin.is_(True)
    rejected = Order.fix_rejected_by_admin.is_(True)
    row = base.with_entities(
        *[func.count(Order.id).filter(upper.in_(states)) for states in TAB_STATES.values()],
        func.count(Order.id).filter(and_(doing, Order.template_missing.is_(True))),
        func.count(Order.id).filter(and_(doing, Order.template_missing.is_(False))),
        func.count(Order.id).filter(and_(fix, ~approved, ~rejected)),
        func.count(Order.id).filter(and_(fix, approved)),
        func.count(Order.id).filter(and_(fix, rejected)),
    ).one()
    values = [int(v or 0) for v in row]
    counts = dict(zip(TAB_STATES, values[:5], strict=True))
    counts.update(
        doing_missing=values[5],
        doing_normal=values[6],
        fix_pending=values[7],
        fix_approved=values[8],
        fix_rejected=values[9],
    )
    return counts


def load_orders_page(
    session: Session, user: User, platform_id: uuid.UUID, p: PageParams
) -> tuple[dict, Query] | None:
    """Counters + the filtered tab query (unordered), or ``None`` when nothing can match."""
    base = visible_orders_query(
        session, user, status=p.status, designer_id=p.designer_id, platform_id=platform_id
    )
    if base is None:
        return None
    tab_cond = tab_condition(p.role, p.tab, p.doing_sub, p.fix_sub)
    tab_query = _apply_filters(base, p).filter(tab_cond)

    # Tab counters ignore every filter except the role/platform scope (as the old client did).
    scope = visible_orders_query(session, user, platform_id=platform_id)
    tab_scope = scope.filter(tab_cond)
    meta: dict = {
        "counts": summary_counts(scope) if p.role == ROLE_ADMIN else _count_by_tab(scope, p.role),
        "aux": {
            "synced_images": tab_scope.filter(
                func.coalesce(func.jsonb_array_length(Order.product_image_urls), 0) > 1
            ).count(),
            "fix_returned": tab_scope.filter(Order.fix_return_count > 0).count(),
        },
    }
    if p.q.strip():
        meta["search_counts"] = _count_by_tab(base.filter(_search_condition(p.q, p.role)), p.role)
    return meta, tab_query


def order_page_query(tab_query: Query, p: PageParams) -> Query:
    column = _date_expr(p.sort_field)
    ordered = column.desc().nulls_last() if p.sort_desc else column.asc().nulls_first()
    keys = [ordered, Order.id]
    if p.role == ROLE_ADMIN and p.tab == "fix" and p.fix_sub == "all":
        triaged = case(
            (or_(Order.fix_approved_by_admin.is_(True), Order.fix_rejected_by_admin.is_(True)), 1),
            else_=0,
        )
        keys.insert(0, triaged)
    return tab_query.order_by(*keys)
