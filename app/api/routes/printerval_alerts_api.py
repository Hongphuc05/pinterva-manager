"""Failed Printerval writes for the Admin web toasts (see ``printerval_alerts``)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.adapters.db.models import User
from app.api.deps import get_current_platform_id, get_db, require_role
from app.application.printerval_alerts import recent_alerts
from app.domain.access import ROLE_ADMIN

router = APIRouter(tags=["printerval-alerts"])

MAX_LOOKBACK = timedelta(days=7)


@router.get("/printerval-alerts")
def list_printerval_alerts(
    since: datetime | None = None,
    _user: User = Depends(require_role(ROLE_ADMIN)),
    platform_id: uuid.UUID = Depends(get_current_platform_id),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Failed writes recorded after ``since`` (default: the last 24 hours, at most 7 days back)."""
    now = datetime.now(UTC)
    if since is None:
        since = now - timedelta(hours=24)
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    since = max(since, now - MAX_LOOKBACK)
    return {"items": recent_alerts(db, platform_id=platform_id, since=since), "now": now}
