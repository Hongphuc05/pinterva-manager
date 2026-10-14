"""Server-side tab/filter/sort/pagination of the Admin order list.

Mirrors what OrdersListPage used to do in the browser over the full order list, so the
Admin loads one page (<=100 orders) instead of every order of the platform.
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

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

TAB_STATES: dict[str, tuple[str, ...]] = {
    "waiting": ("WAITING", "OPEN_FOR_ALLOCATION", "DISCOVERED", "PENDING", "OPEN"),
    "doing": ("IN_PROGRESS", "DOING", "ASSIGNED"),
    "review": ("QC_PENDING", "RESULT_SUBMITTED", "SUBMITTING_TO_SITE", "REVIEW"),
    "fix": ("REVISION", "REVISION_REQUESTED", "FIX"),
    "done": ("DONE", "CLAIMED_IMPORTED", "COMPLETED", "SKIPPED"),
}
TAB_ORDER = ("review", "fix", "doing", "waiting", "done")  # which tab a search jumps to first
DATE_FIELDS = ("status_changed_at", "order_created_at_ext", "created_at")
MAX_PAGE_SIZE = 200
MAX_IDS = 5000


@dataclass
class PageParams:
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
    only_ids: list[uuid.UUID] | None = None
    sort_field: str = "status_changed_at"
    sort_desc: bool = True
    page: int = 1
    page_size: int = 100


def _upper_state():
    return func.upper(Order.state)


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


def _search_condition(q: str):
    pattern = _like(q.strip())
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
        query = query.filter(_search_condition(p.q))
    if p.platform_status:
        wanted = p.platform_status.strip().lower()
        if wanted == "unspecified":
            query = query.filter(or_(Order.printerval_status.is_(None), Order.printerval_status == ""))
        else:
            query = query.filter(func.lower(func.trim(Order.printerval_status)) == wanted)
    if p.batch and p.batch.strip():
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
    if p.only_ids is not None:
        query = query.filter(Order.id.in_(p.only_ids))
    return query


def _count_by_tab(query: Query) -> dict[str, int]:
    upper = _upper_state()
    columns = [func.count(Order.id).filter(upper.in_(states)).label(tab) for tab, states in TAB_STATES.items()]
    row = query.with_entities(*columns).one()
    return {tab: int(row[i] or 0) for i, tab in enumerate(TAB_STATES)}


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


def load_admin_page(
    session: Session, admin: User, platform_id: uuid.UUID, p: PageParams
) -> tuple[dict, Query] | None:
    """Counters + the filtered tab query (unordered), or ``None`` when nothing can match."""
    base = visible_orders_query(
        session, admin, status=p.status, designer_id=p.designer_id, platform_id=platform_id
    )
    if base is None:
        return None
    tab_cond = _tab_condition(p.tab, p.doing_sub, p.fix_sub)
    tab_query = _apply_filters(base, p).filter(tab_cond)

    # Tab counters ignore every filter except the role/platform scope (as the old client did).
    scope = visible_orders_query(session, admin, platform_id=platform_id)
    tab_scope = scope.filter(tab_cond)
    meta: dict = {
        "counts": summary_counts(scope),
        "aux": {
            "synced_images": tab_scope.filter(
                func.coalesce(func.jsonb_array_length(Order.product_image_urls), 0) > 1
            ).count(),
            "fix_returned": tab_scope.filter(Order.fix_return_count > 0).count(),
        },
    }
    if p.q.strip():
        meta["search_counts"] = _count_by_tab(base.filter(_search_condition(p.q)))
    return meta, tab_query


def order_page_query(tab_query: Query, p: PageParams) -> Query:
    column = _date_expr(p.sort_field)
    ordered = column.desc().nulls_last() if p.sort_desc else column.asc().nulls_first()
    keys = [ordered, Order.id]
    if p.tab == "fix" and p.fix_sub == "all":
        triaged = case(
            (or_(Order.fix_approved_by_admin.is_(True), Order.fix_rejected_by_admin.is_(True)), 1),
            else_=0,
        )
        keys.insert(0, triaged)
    return tab_query.order_by(*keys)
