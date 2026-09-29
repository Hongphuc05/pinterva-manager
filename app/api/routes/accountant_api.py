"""The Accountant's payment page: Designers waiting for payment, their orders, and paying them.

Amounts come from the same credit rules the Admin finance page uses (``credited_tasks``), and a
payment goes through the one path Admin uses (``pay_orders``). Per-order rates are never sent:
the Accountant sees how many orders and the total only.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.adapters.db.models import User, UserBankQr
from app.api.deps import get_current_platform_id, get_db, require_role
from app.application.payments import PaymentConflictError, pay_orders, pending_tasks
from app.application.sanitization import encode_proxy_url
from app.domain.access import ROLE_ACCOUNTANT

router = APIRouter(prefix="/accountant", tags=["accountant"])


class PendingDesignerOut(BaseModel):
    designer_id: str
    designer_name: str
    username: str | None
    pending_count: int
    pending_amount: int
    has_qr: bool


class PendingOrderOut(BaseModel):
    order_id: str
    external_order_id: str
    product_name: str | None
    thumbnail_url: str | None
    submitted_at: datetime | None


class PendingDesignerDetailOut(PendingDesignerOut):
    orders: list[PendingOrderOut]


class PayRequest(BaseModel):
    order_ids: list[uuid.UUID] = Field(min_length=1)
    expected_total: int = Field(ge=0)


def _designer_rows(db: Session, platform_id: uuid.UUID) -> dict[str, list]:
    grouped: dict[str, list] = defaultdict(list)
    for task in pending_tasks(db, platform_id):
        grouped[task.designer_id].append(task)
    return grouped


def _summary(db: Session, designer_id: str, tasks: list, qr_owners: set[uuid.UUID]) -> PendingDesignerOut:
    user = db.get(User, uuid.UUID(designer_id))
    return PendingDesignerOut(
        designer_id=designer_id,
        designer_name=tasks[0].designer_name,
        username=user.username if user else None,
        pending_count=len(tasks),
        pending_amount=sum(t.rate for t in tasks),
        has_qr=uuid.UUID(designer_id) in qr_owners,
    )


def _qr_owners(db: Session, user_ids: list[str]) -> set[uuid.UUID]:
    ids = [uuid.UUID(i) for i in user_ids]
    if not ids:
        return set()
    return {row[0] for row in db.query(UserBankQr.user_id).filter(UserBankQr.user_id.in_(ids)).distinct().all()}


@router.get("/designers", response_model=list[PendingDesignerOut])
def list_pending_designers(
    _: User = Depends(require_role(ROLE_ACCOUNTANT)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Designers with orders waiting for payment, most orders first."""
    grouped = _designer_rows(db, platform_id)
    owners = _qr_owners(db, list(grouped))
    rows = [_summary(db, designer_id, tasks, owners) for designer_id, tasks in grouped.items()]
    return sorted(rows, key=lambda r: (-r.pending_count, r.designer_name))


@router.get("/designers/{designer_id}", response_model=PendingDesignerDetailOut)
def get_pending_designer(
    designer_id: uuid.UUID,
    _: User = Depends(require_role(ROLE_ACCOUNTANT)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    tasks = _designer_rows(db, platform_id).get(str(designer_id), [])
    if not tasks:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Designer này không còn đơn chờ thanh toán.")
    summary = _summary(db, str(designer_id), tasks, _qr_owners(db, [str(designer_id)]))
    tasks = sorted(tasks, key=lambda t: t.first_submitted_at or datetime.min, reverse=True)
    return PendingDesignerDetailOut(
        **summary.model_dump(),
        orders=[
            PendingOrderOut(
                order_id=t.order_id,
                external_order_id=t.external_order_id,
                product_name=t.product_name,
                thumbnail_url=encode_proxy_url(t.thumbnail_url) if t.thumbnail_url else None,
                submitted_at=t.first_submitted_at,
            )
            for t in tasks
        ],
    )


@router.post("/designers/{designer_id}/pay")
def pay_designer(
    designer_id: uuid.UUID,
    payload: PayRequest,
    user: User = Depends(require_role(ROLE_ACCOUNTANT)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    """Pay exactly the orders the Accountant saw, for exactly the total they transferred.

    Orders that arrived since the popup opened are not touched (they wait for the next
    payment). Any shown order already paid, no longer this Designer's, or a changed amount
    refuses the whole payment, so the recorded amount always equals the transferred one.
    """
    pending = {t.order_id for t in _designer_rows(db, platform_id).get(str(designer_id), [])}
    if any(str(order_id) not in pending for order_id in payload.order_ids):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Danh sách đơn đã thay đổi (có đơn đã được thanh toán hoặc không còn của designer này). Hãy mở lại.",
        )
    try:
        result = pay_orders(
            db,
            actor=user,
            platform_id=platform_id,
            order_ids=payload.order_ids,
            expected_total=payload.expected_total,
        )
    except PaymentConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{exc} Hãy mở lại.") from exc
    return {
        "ok": True,
        "paid_count": result.updated_count,
        "total_amount": sum(b.total_amount for b in result.batches),
    }
