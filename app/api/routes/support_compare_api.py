"""Web entry for Support's duplicate check (same job as the Telegram /check command)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import get_db, require_role
from app.application.support_compare import (
    count_handleable_orders,
    count_support_unchecked_orders,
    create_support_compare_job,
)
from app.config import get_settings
from app.domain.access import ROLE_SUPPORT

router = APIRouter()


class SupportCompareStatusOut(BaseModel):
    enabled: bool
    new_orders: int
    handleable_orders: int


class SupportCompareCheckOut(BaseModel):
    job_id: str
    requested_count: int


@router.get("/support-compare/status", response_model=SupportCompareStatusOut)
def api_support_compare_status(
    user: User = Depends(require_role(ROLE_SUPPORT)),
    db: Session = Depends(get_db),
):
    if user.platform_id is None or not get_settings().support_compare_enabled:
        return SupportCompareStatusOut(enabled=False, new_orders=0, handleable_orders=0)
    return SupportCompareStatusOut(
        enabled=True,
        new_orders=count_support_unchecked_orders(db, platform_id=user.platform_id),
        handleable_orders=count_handleable_orders(db, platform_id=user.platform_id),
    )


@router.post("/support-compare/check", response_model=SupportCompareCheckOut)
def api_support_compare_check(
    user: User = Depends(require_role(ROLE_SUPPORT)),
    db: Session = Depends(get_db),
):
    """Queue the never-compared orders for the local worker (Telegram /check → Có)."""
    if not get_settings().support_compare_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Chức năng kiểm tra trùng đang tắt trên hệ thống.")
    if user.platform_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tài khoản Support chưa được gắn platform.")
    if not user.telegram_chat_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cần liên kết Telegram: báo cáo kết quả và cặp ảnh xác nhận được gửi qua Telegram.",
        )
    job = create_support_compare_job(
        db,
        platform_id=user.platform_id,
        requested_by_id=user.id,
        chat_id=str(user.telegram_chat_id),
    )
    if job is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Không có đơn mới nào cần kiểm tra.")
    db.commit()
    return SupportCompareCheckOut(job_id=str(job.id), requested_count=job.requested_count)
