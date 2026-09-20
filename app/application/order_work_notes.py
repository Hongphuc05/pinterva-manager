"""Private, append-only work notes shared by an order's operators."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.db.models import OrderWorkNote, OrderWorkNoteAttachment, User

MAX_IMAGES_PER_NOTE = 5
MAX_IMAGE_BYTES = 10 * 1024 * 1024
PRIVATE_WORK_NOTE_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "private_work_note_assets"


def _image_type(content: bytes) -> tuple[str, str] | None:
    """Accept only formats browsers safely render as raster images."""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def _safe_filename(filename: str | None, extension: str) -> str:
    raw_name = Path(filename or "image").name.strip() or "image"
    return f"{raw_name[:220]}{extension}" if not raw_name.lower().endswith(extension) else raw_name[:255]


async def create_work_note(
    session: Session,
    *,
    order_id: uuid.UUID,
    author: User,
    body: str,
    idempotency_key: str,
    images: list[UploadFile],
) -> OrderWorkNote:
    clean_body = body.strip()
    if not clean_body and not images:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cần nhập ghi chú hoặc dán ít nhất một ảnh.")
    if len(images) > MAX_IMAGES_PER_NOTE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Tối đa {MAX_IMAGES_PER_NOTE} ảnh cho một cập nhật.")

    existing = (
        session.query(OrderWorkNote)
        .filter_by(order_id=order_id, author_id=author.id, idempotency_key=idempotency_key)
        .one_or_none()
    )
    if existing is not None:
        return existing

    validated_images: list[tuple[UploadFile, bytes, str, str]] = []
    for image in images:
        content = await image.read()
        if not content or len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Mỗi ảnh tối đa 10 MB.")
        detected = _image_type(content)
        if detected is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Chỉ chấp nhận ảnh PNG, JPEG hoặc WebP.")
        content_type, extension = detected
        validated_images.append((image, content, content_type, extension))

    note = OrderWorkNote(
        order_id=order_id,
        author_id=author.id,
        body=clean_body,
        idempotency_key=idempotency_key,
    )
    session.add(note)
    session.flush()

    written_paths: list[Path] = []
    try:
        note_dir = PRIVATE_WORK_NOTE_ASSETS_DIR / str(order_id) / str(note.id)
        note_dir.mkdir(parents=True, exist_ok=True)
        for image, content, content_type, extension in validated_images:
            file_id = uuid.uuid4()
            target = note_dir / f"{file_id}{extension}"
            with target.open("xb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            written_paths.append(target)
            session.add(OrderWorkNoteAttachment(
                note_id=note.id,
                storage_key=str(target.relative_to(PRIVATE_WORK_NOTE_ASSETS_DIR)),
                original_filename=_safe_filename(image.filename, extension),
                content_type=content_type,
                byte_size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            ))
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = (
            session.query(OrderWorkNote)
            .filter_by(order_id=order_id, author_id=author.id, idempotency_key=idempotency_key)
            .one_or_none()
        )
        if existing is not None:
            return existing
        raise
    except Exception:
        session.rollback()
        for path in written_paths:
            path.unlink(missing_ok=True)
        raise
    session.refresh(note)
    return note
