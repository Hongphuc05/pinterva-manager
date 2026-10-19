"""Mockup images a Designer attaches to a submission (required since Printerval's 19/10 rule).

Printerval refuses to move a job to Review unless its Design column holds an image. The Designer adds
1 to ``MAX_RESULT_IMAGES`` images in Tacahu: each is staged first (uploaded, not yet used), the
submission attaches them, and the Review push uploads every attached image not yet on Printerval
(``images_to_push``). Bytes are private (same volume as work-note images); only metadata is in the DB.
"""

from __future__ import annotations

import hashlib
import os
import struct
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.adapters.db.models import Order, ResultImage, User
from app.application.order_work_notes import PRIVATE_WORK_NOTE_ASSETS_DIR, _safe_filename

MAX_RESULT_IMAGES = 3
MAX_RESULT_IMAGE_BYTES = 10 * 1024 * 1024
RESULT_IMAGES_DIR = PRIVATE_WORK_NOTE_ASSETS_DIR / "result_images"


class ResultImageError(ValueError):
    """A request about result images that cannot be honoured; the message is shown to the user."""


def image_kind(content: bytes) -> tuple[str, str] | None:
    """PNG or JPEG only: what Printerval's Design column takes as a mockup."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    return None


def image_size(content: bytes) -> tuple[int, int] | None:
    """Width and height read from the PNG header or the JPEG frame marker (no image library needed)."""
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        width, height = struct.unpack(">II", content[16:24])
        return width, height
    if content.startswith(b"\xff\xd8"):
        i = 2
        while i + 9 < len(content):
            if content[i] != 0xFF:
                i += 1
                continue
            marker = content[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", content[i + 2:i + 4])[0]
            # SOF0..SOF15 except DHT (C4), JPG (C8) and DAC (CC) carry the frame size.
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", content[i + 5:i + 9])
                return width, height
            i += 2 + length
    return None


def image_path(image: ResultImage) -> Path:
    return PRIVATE_WORK_NOTE_ASSETS_DIR / image.storage_key


def stage_images(session: Session, order: Order, user: User, files: list[tuple[str | None, bytes]]) -> list[ResultImage]:
    """Validate and store images for a coming submission. The caller commits."""
    if not files:
        raise ResultImageError("Chọn ít nhất 1 ảnh mockup")
    staged = staged_images(session, order, user)
    if len(staged) + len(files) > MAX_RESULT_IMAGES:
        raise ResultImageError(f"Tối đa {MAX_RESULT_IMAGES} ảnh mockup cho một lần nộp")
    checked = []
    for filename, content in files:
        if not content or len(content) > MAX_RESULT_IMAGE_BYTES:
            raise ResultImageError("Mỗi ảnh mockup tối đa 10 MB")
        kind = image_kind(content)
        if kind is None:
            raise ResultImageError("Ảnh mockup phải là PNG hoặc JPEG")
        checked.append((filename, content, *kind))

    folder = RESULT_IMAGES_DIR / str(order.id)
    folder.mkdir(parents=True, exist_ok=True)
    images = []
    for filename, content, content_type, extension in checked:
        target = folder / f"{uuid.uuid4()}{extension}"
        with target.open("xb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        size = image_size(content)
        image = ResultImage(
            order_id=order.id,
            uploaded_by_id=user.id,
            storage_key=str(target.relative_to(PRIVATE_WORK_NOTE_ASSETS_DIR)),
            original_filename=_safe_filename(filename, extension),
            content_type=content_type,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            width=size[0] if size else None,
            height=size[1] if size else None,
        )
        session.add(image)
        images.append(image)
    session.flush()
    return images


def staged_images(session: Session, order: Order, user: User) -> list[ResultImage]:
    return (
        session.query(ResultImage)
        .filter(
            ResultImage.order_id == order.id,
            ResultImage.uploaded_by_id == user.id,
            ResultImage.attached_at.is_(None),
        )
        .order_by(ResultImage.created_at)
        .all()
    )


def discard_staged_image(session: Session, order: Order, user: User, image_id: uuid.UUID) -> None:
    """Remove an image the user staged and has not submitted yet. The caller commits."""
    image = session.get(ResultImage, image_id)
    if image is None or image.order_id != order.id or image.uploaded_by_id != user.id:
        raise LookupError("Không tìm thấy ảnh")
    if image.attached_at is not None:
        raise ResultImageError("Ảnh đã nộp, không xoá được")
    image_path(image).unlink(missing_ok=True)
    session.delete(image)


def attach_images(session: Session, order: Order, user: User, image_ids: list[str] | None) -> list[ResultImage]:
    """Use 1 to 3 staged images of this user for the submission being recorded. The caller commits."""
    ids = list(dict.fromkeys(image_ids or []))
    if not ids:
        raise ResultImageError("Cần gắn ít nhất 1 ảnh mockup trước khi nộp bài (Printerval bắt buộc)")
    if len(ids) > MAX_RESULT_IMAGES:
        raise ResultImageError(f"Tối đa {MAX_RESULT_IMAGES} ảnh mockup cho một lần nộp")
    try:
        wanted = {uuid.UUID(str(i)) for i in ids}
    except ValueError as exc:
        raise ResultImageError("Ảnh mockup không hợp lệ") from exc
    images = [
        image for image in staged_images(session, order, user) if image.id in wanted
    ]
    if len(images) != len(wanted):
        raise ResultImageError("Ảnh mockup không còn hoặc đã được dùng, hãy gắn lại")
    now = datetime.now(UTC)
    for image in images:
        image.attached_at = now
    return images


def images_to_push(session: Session, order: Order) -> list[ResultImage]:
    """Submitted images of the order not yet on Printerval, oldest first."""
    return (
        session.query(ResultImage)
        .filter(
            ResultImage.order_id == order.id,
            ResultImage.attached_at.isnot(None),
            ResultImage.pushed_at.is_(None),
        )
        .order_by(ResultImage.attached_at, ResultImage.created_at)
        .all()
    )


def submitted_images(session: Session, order: Order) -> list[ResultImage]:
    """Every submitted image of the order, newest submission first (for the order page)."""
    return (
        session.query(ResultImage)
        .filter(ResultImage.order_id == order.id, ResultImage.attached_at.isnot(None))
        .order_by(ResultImage.attached_at.desc(), ResultImage.created_at)
        .all()
    )
