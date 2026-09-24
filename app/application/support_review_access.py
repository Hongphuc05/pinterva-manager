"""Password of the hidden duplicate-review area.

The review pages are not linked anywhere; a Support who knows the address must also know this
password (one per platform, changeable from inside the area). Unlocking returns a signed token
that the web keeps for the browser session. It stops working when the password changes, or after
12 hours. Repeated wrong passwords lock the area for a few minutes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.adapters.db.models import SupportReviewAccess, User
from app.application.auth import hash_password, verify_password
from app.config import get_settings

MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_LENGTH = 128
MAX_FAILED_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=10)
TOKEN_MAX_AGE_SECONDS = 12 * 3600
_SALT = "support-review-unlock"


class ReviewAccessError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt=_SALT)


def _check_new_password(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ReviewAccessError(
            "weak_password", f"Mật khẩu phải từ {MIN_PASSWORD_LENGTH} đến {MAX_PASSWORD_LENGTH} ký tự.", 422
        )


def get_access(session: Session, platform_id: uuid.UUID) -> SupportReviewAccess | None:
    return session.get(SupportReviewAccess, platform_id)


def issue_token(user: User, access: SupportReviewAccess) -> str:
    return _serializer().dumps({"u": str(user.id), "p": str(access.platform_id), "v": access.version})


def token_is_valid(session: Session, user: User, platform_id: uuid.UUID, token: str | None) -> bool:
    access = get_access(session, platform_id)
    if not token or access is None:
        return False
    try:
        data = _serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return False
    return data.get("u") == str(user.id) and data.get("p") == str(platform_id) and data.get("v") == access.version


def set_initial_password(session: Session, *, user: User, platform_id: uuid.UUID, password: str) -> str:
    """First use only: whoever opens the hidden area first chooses its password."""
    if get_access(session, platform_id) is not None:
        raise ReviewAccessError("already_set", "Đã có mật khẩu. Hãy nhập mật khẩu để mở.", 409)
    _check_new_password(password)
    access = SupportReviewAccess(
        platform_id=platform_id, password_hash=hash_password(password), updated_by_id=user.id
    )
    session.add(access)
    session.flush()
    return issue_token(user, access)


def _verify(session: Session, access: SupportReviewAccess, password: str) -> None:
    now = _now()
    if access.locked_until and access.locked_until > now:
        raise ReviewAccessError("locked_out", "Nhập sai quá nhiều lần. Thử lại sau vài phút.", 429)
    if verify_password(password, access.password_hash):
        access.failed_attempts = 0
        access.locked_until = None
        return
    access.failed_attempts += 1
    if access.failed_attempts >= MAX_FAILED_ATTEMPTS:
        access.locked_until = now + LOCKOUT
        access.failed_attempts = 0
    session.commit()  # keep the counter even though the request fails
    raise ReviewAccessError("wrong_password", "Mật khẩu không đúng.", 403)


def unlock(session: Session, *, user: User, platform_id: uuid.UUID, password: str) -> str:
    access = get_access(session, platform_id)
    if access is None:
        raise ReviewAccessError("not_set", "Chưa đặt mật khẩu.", 409)
    _verify(session, access, password)
    return issue_token(user, access)


def change_password(
    session: Session, *, user: User, platform_id: uuid.UUID, current: str, new: str
) -> str:
    access = get_access(session, platform_id)
    if access is None:
        raise ReviewAccessError("not_set", "Chưa đặt mật khẩu.", 409)
    _verify(session, access, current)
    _check_new_password(new)
    access.password_hash = hash_password(new)
    access.version += 1  # every token issued before this stops working
    access.updated_by_id = user.id
    access.updated_at = _now()
    session.flush()
    return issue_token(user, access)
