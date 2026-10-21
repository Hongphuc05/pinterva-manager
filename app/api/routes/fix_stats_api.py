"""Admin: how often each Designer's work comes back as a Fix (see ``app.application.fix_stats``)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import get_current_platform_id, get_db, require_role
from app.application.fix_stats import (
    FIX_HISTORY_SINCE,
    REPEAT_WARNING,
    designer_fix_stats,
    designer_fixed_orders,
)
from app.domain.access import ROLE_ADMIN

router = APIRouter(tags=["fix-stats"])


def _check(date_from: date | None, date_to: date | None) -> dict:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ngày bắt đầu phải trước ngày kết thúc.")
    return {
        "since": FIX_HISTORY_SINCE,
        "incomplete": date_from is None or date_from < FIX_HISTORY_SINCE,
        "repeat_threshold": REPEAT_WARNING,
    }


@router.get("/designers/fix-stats")
def api_designer_fix_stats(
    date_from: date | None = None,
    date_to: date | None = None,
    _user: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict:
    """Per Designer: orders first submitted in the period, how many came back as a Fix, and how often."""
    meta = _check(date_from, date_to)
    return {**meta, "designers": designer_fix_stats(db, platform_id, date_from, date_to)}


@router.get("/designers/{designer_id}/fix-stats")
def api_designer_fixed_orders(
    designer_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    _user: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict:
    """That Designer's Fixed orders of the period, each Fix with its time, reason and whether it counts."""
    meta = _check(date_from, date_to)
    return {**meta, "orders": designer_fixed_orders(db, platform_id, designer_id, date_from, date_to)}
