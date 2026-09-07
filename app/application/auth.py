from __future__ import annotations

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings


def hash_password(raw_password: str) -> str:
    return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(raw_password.encode("utf-8"), password_hash.encode("utf-8"))


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.secret_key, salt="session-cookie")


def create_session_token(user_id: str, role: str) -> str:
    return _serializer().dumps({"user_id": user_id, "role": role})


def read_session_token(token: str) -> dict | None:
    settings = get_settings()
    try:
        return _serializer().loads(token, max_age=settings.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None


def ensure_seed_users(db: Session) -> None:
    """Ensure seed users exist in DB."""
    from app.adapters.db.models import User
    from sqlalchemy.exc import IntegrityError

    admin_user = db.query(User).filter_by(username="admin").first()
    if admin_user is None:
        try:
            admin_user = User(
                username="admin",
                full_name="System Administrator",
                role="admin",
                password_hash=hash_password("admin123"),
                active=True,
            )
            db.add(admin_user)
            db.commit()
        except IntegrityError:
            db.rollback()

