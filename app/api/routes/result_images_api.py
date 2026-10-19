"""Mockup images for a submission (see ``result_images``): staged by the Designer, then submitted."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.adapters.db.models import Order, ResultImage, User
from app.api.deps import get_current_platform_id, get_db, require_any_role
from app.application.order_queries import get_order_detail_for_user
from app.application.result_images import (
    MAX_RESULT_IMAGE_BYTES,
    MAX_RESULT_IMAGES,
    ResultImageError,
    discard_staged_image,
    image_path,
    stage_images,
    staged_images,
    submitted_images,
)
from app.domain.access import ROLE_ADMIN, ROLE_DESIGNER, ROLE_DESIGNER_TRELLO

router = APIRouter(tags=["result-images"])
ROLES = (ROLE_ADMIN, ROLE_DESIGNER, ROLE_DESIGNER_TRELLO)


def _order(db: Session, user: User, order_id: uuid.UUID, platform_id: uuid.UUID) -> Order:
    """Same reach as the order page: Admin, the order's Designer, any Trello Designer on duplicates."""
    order = get_order_detail_for_user(
        db, user, str(order_id), allow_shared_trello=user.role == ROLE_DESIGNER_TRELLO, platform_id=platform_id
    )
    if order is None or (order.platform_id is not None and order.platform_id != platform_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy đơn hàng")
    return order


def _out(order: Order, image: ResultImage) -> dict[str, Any]:
    return {
        "id": str(image.id),
        "filename": image.original_filename,
        "width": image.width,
        "height": image.height,
        "submitted_at": image.attached_at,
        "on_printerval": image.pushed_at is not None,
        "url": f"/api/orders/{order.id}/result-images/{image.id}/file",
    }


@router.get("/orders/{order_id}/result-images")
def list_result_images(
    order_id: uuid.UUID,
    user: User = Depends(require_any_role(*ROLES)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The caller's staged images (not submitted yet) and every submitted image of the order."""
    order = _order(db, user, order_id, platform_id)
    return {
        "staged": [_out(order, i) for i in staged_images(db, order, user)],
        "submitted": [_out(order, i) for i in submitted_images(db, order)],
        "max_images": MAX_RESULT_IMAGES,
    }


@router.post("/orders/{order_id}/result-images", status_code=status.HTTP_201_CREATED)
async def upload_result_images(
    order_id: uuid.UUID,
    images: list[UploadFile] = File(...),
    user: User = Depends(require_any_role(*ROLES)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    order = _order(db, user, order_id, platform_id)
    files = []
    for upload in images[: MAX_RESULT_IMAGES + 1]:
        content = await upload.read(MAX_RESULT_IMAGE_BYTES + 1)
        files.append((upload.filename, content))
    try:
        stage_images(db, order, user, files)
    except ResultImageError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    db.commit()
    return {"staged": [_out(order, i) for i in staged_images(db, order, user)]}


@router.delete("/orders/{order_id}/result-images/{image_id}")
def delete_result_image(
    order_id: uuid.UUID,
    image_id: uuid.UUID,
    user: User = Depends(require_any_role(*ROLES)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    order = _order(db, user, order_id, platform_id)
    try:
        discard_staged_image(db, order, user, image_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ResultImageError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    return {"staged": [_out(order, i) for i in staged_images(db, order, user)]}


@router.get("/orders/{order_id}/result-images/{image_id}/file")
def get_result_image_file(
    order_id: uuid.UUID,
    image_id: uuid.UUID,
    user: User = Depends(require_any_role(*ROLES)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
):
    order = _order(db, user, order_id, platform_id)
    image = db.get(ResultImage, image_id)
    # Someone else's staged image stays private until it is submitted.
    if image is None or image.order_id != order.id or (image.attached_at is None and image.uploaded_by_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy ảnh")
    path = image_path(image)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy ảnh")
    return FileResponse(
        path,
        media_type=image.content_type,
        filename=image.original_filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
