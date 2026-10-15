"""Failed writes to Printerval, kept as DeadLetters and shown to Admin as web toasts.

A write that did not go through (Review/status, note, Designer) must never be silent: it is recorded
here with what to do by hand, and the Admin web polls ``recent_alerts`` to toast each one.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.adapters.db.models import DeadLetter, Order

logger = logging.getLogger(__name__)

ALERT_SOURCE = "printerval.write_failed"


def record_write_failure(
    session: Session,
    order: Order,
    *,
    action: str,
    error: str,
    manual: str,
    error_class: str = "UNKNOWN_OUTCOME",
) -> None:
    """Record one failed Printerval write for the Admin toasts. Never raises."""
    try:
        session.add(
            DeadLetter(
                source=ALERT_SOURCE,
                payload={
                    "order_id": str(order.id),
                    "order_code": order.external_order_id,
                    "platform_id": str(order.platform_id) if order.platform_id else None,
                    "action": action,
                    "error": error[:500],
                },
                error_class=error_class[:64],
                recovery_action=manual[:512],
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("could not record the failed Printerval write for %s", order.external_order_id)


def recent_alerts(session: Session, *, platform_id: uuid.UUID, since: datetime, limit: int = 50) -> list[dict]:
    """Failed writes of this platform recorded after ``since``, oldest first."""
    rows = (
        session.query(DeadLetter)
        .filter(DeadLetter.source == ALERT_SOURCE, DeadLetter.created_at > since)
        .order_by(DeadLetter.created_at.asc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    out = []
    for row in rows:
        payload = row.payload or {}
        if payload.get("platform_id") != str(platform_id):
            continue
        out.append(
            {
                "id": str(row.id),
                "created_at": row.created_at,
                "order_id": payload.get("order_id"),
                "order_code": payload.get("order_code"),
                "action": payload.get("action"),
                "error": payload.get("error"),
                "error_class": row.error_class,
                "manual": row.recovery_action,
            }
        )
    return out
