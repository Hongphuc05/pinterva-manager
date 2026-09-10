from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import Platform, PlatformSyncState
from app.adapters.errors import ErrorClass
from app.adapters.printerval.api_client import (
    PrintervalApiClient,
    PrintervalApiConfigurationError,
    PrintervalApiError,
)
from app.config import get_settings


class PlatformCredentialsError(ValueError):
    """A supplied Printerval account/session could not be verified."""


def verify_and_save_platform_credentials(
    db: Session,
    *,
    platform: Platform,
    username: str,
    password: str | None,
    team_outsource: str | None,
    session_cookie: str | None,
) -> Platform:
    """Verify credentials before persisting them to one Platform row.

    The browser never receives the stored values. A successful verification also clears
    the stale background-sync error for this same platform only.
    """

    username_clean = username.strip()
    password_clean = password.strip() if password else None
    team_clean = team_outsource.strip() if team_outsource else None
    cookie_clean = session_cookie.strip() if session_cookie else None
    if not username_clean:
        raise PlatformCredentialsError("Email / username Printerval không được để trống.")

    effective_password = password_clean or platform.account_password
    effective_team = team_clean or platform.team_outsource
    effective_cookie = cookie_clean or platform.session_cookie
    settings = get_settings()
    client = PrintervalApiClient(
        base_url=settings.printerval_api_base_url,
        username=username_clean,
        password=effective_password,
        team_outsource=effective_team,
        session_cookie=effective_cookie,
    )
    try:
        client.login()
        client.discover_waiting_page(page_size=1)
    except PrintervalApiConfigurationError as exc:
        raise PlatformCredentialsError(str(exc)) from exc
    except PrintervalApiError as exc:
        if exc.error_class == ErrorClass.AUTH:
            raise PlatformCredentialsError(
                "Xác thực Printerval không thành công. Kiểm tra Session Cookie hoặc username/mật khẩu."
            ) from exc
        raise PlatformCredentialsError(
            f"Xác thực thành công nhưng Team Outsource có vẻ không đúng: {exc}"
        ) from exc
    finally:
        client.close()

    platform.account_username = username_clean
    if password_clean:
        platform.account_password = password_clean
    if team_clean:
        platform.team_outsource = team_clean
    if cookie_clean:
        platform.session_cookie = cookie_clean
    platform.is_active = True

    sync_state = db.get(PlatformSyncState, platform.id)
    if sync_state is not None:
        sync_state.last_error = None
    db.commit()
    db.refresh(platform)
    return platform


def find_platform_by_account(db: Session, username: str) -> Platform | None:
    return db.query(Platform).filter(Platform.account_username == username.strip()).one_or_none()


def ensure_platform_for_account(db: Session, username: str) -> Platform:
    platform = find_platform_by_account(db, username)
    if platform is not None:
        return platform
    platform = Platform(
        id=uuid.uuid4(),
        name=f"Acc Mẹ: {username.strip()}",
        account_username=username.strip(),
        is_active=True,
    )
    db.add(platform)
    db.flush()
    return platform
