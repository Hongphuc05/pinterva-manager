"""Per-order, auditable Printerval Designer/Status synchronization."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.adapters.db.models import (
    ExternalObservation,
    Order,
    Platform,
    PrintervalAssignmentRequest,
    User,
)
from app.adapters.playwright_support import with_retry
from app.adapters.printerval.interface import PrintervalAdapter
from app.application.operations import run_idempotent

PRINTERVAL_STATUSES = ("Waiting", "Doing", "Review", "Fix", "Confirm", "Done")


class PrintervalAssignmentValidationError(ValueError):
    pass


def normalize_printerval_status(status: str | None) -> str:
    """Return the canonical external status while accepting stored UI values.

    Older crawls store lowercase statuses (for example ``waiting``), while the
    assignment command uses title-cased values.  The external integration only
    accepts the latter, so normalize at the application boundary rather than
    making every caller know the exact casing.
    """
    candidate = (status or "").strip()
    for allowed in PRINTERVAL_STATUSES:
        if allowed.lower() == candidate.lower():
            return allowed
    raise PrintervalAssignmentValidationError("Invalid Printerval status")


def create_request(
    session: Session,
    *,
    order: Order,
    internal_designer: User,
    platform_id,
    designer_option: str | None,
    target_status: str,
    commit: bool = True,
) -> PrintervalAssignmentRequest:
    """Persist an auditable external-sync intent.

    Most callers own a single request and keep the historical immediate-commit
    behavior.  A larger business transaction can pass ``commit=False`` so its
    internal state change and the durable external-sync intent commit atomically.
    """
    if order.platform_id != platform_id:
        raise PrintervalAssignmentValidationError("Order does not belong to the active platform")
    # A request can update both the external Designer and status, or only the
    # status. Keep the latter in the same durable request lifecycle so the UI can
    # show a verified outcome instead of treating a queued Celery task as success.
    designer_option = (designer_option or "").strip()
    target_status = normalize_printerval_status(target_status)
    request = PrintervalAssignmentRequest(
        order_id=order.id,
        platform_id=platform_id,
        internal_designer_id=internal_designer.id,
        designer_option=designer_option,
        target_status=target_status,
    )
    session.add(request)
    if commit:
        session.commit()
    else:
        # Allocate the request id before the caller commits its enclosing
        # transaction, so it can dispatch the worker only after that commit.
        session.flush()
    return request


def _match_designer_option(requested: str, available: list[str]) -> str | None:
    if not requested or not available:
        return None
    req_clean = requested.strip().lower()
    # 1. Exact case-insensitive match
    for opt in available:
        if opt.strip().lower() == req_clean:
            return opt
    # 2. Substring match
    for opt in available:
        opt_clean = opt.strip().lower()
        if req_clean in opt_clean or opt_clean in req_clean:
            return opt
    # 3. Keyword matching for common designer names
    keywords = ("thúy hường", "thuy huong", "thuý hường")
    if any(kw in req_clean for kw in keywords):
        for opt in available:
            opt_clean = opt.strip().lower()
            if any(kw in opt_clean for kw in keywords):
                return opt
    return None


def execute_request(
    session: Session, adapter: PrintervalAdapter, request: PrintervalAssignmentRequest
) -> dict:
    """Apply Designer then Status, recording each independently verified outcome."""
    order = session.get(Order, request.order_id)
    if order is None:
        request.lifecycle = "failed"
        request.error_class = "VALIDATION"
        request.error_message = "Order was deleted before external synchronization"
        session.commit()
        return {"lifecycle": request.lifecycle}

    fingerprint = hashlib.sha256(
        f"{request.id}:{request.designer_option}:{request.target_status}".encode()
    ).hexdigest()

    def _do() -> dict:
        designer_failure: str | None = None
        platform = session.get(Platform, request.platform_id)
        if request.designer_option:
            available_designers = platform.printerval_designer_options if platform else None
            # If cache is missing on platform, try loading it from api_client if available
            if not available_designers and hasattr(adapter, "api_client") and getattr(adapter, "api_client", None):
                try:
                    available_designers = adapter.api_client.list_designer_options()
                    if platform and available_designers:
                        platform.printerval_designer_options = available_designers
                        session.commit()
                except Exception:
                    pass

            target_designer_opt = request.designer_option
            if available_designers:
                matched_designer = _match_designer_option(request.designer_option, available_designers)
                if not matched_designer:
                    # If this specific designer is no longer available on this platform, fail fast
                    return _fail(
                        request,
                        "EXTERNAL_CHANGED",
                        "Selected Printerval Designer is no longer available for this platform",
                        {"available_designers": available_designers},
                    )
                target_designer_opt = matched_designer

            designer_result = with_retry(
                lambda: adapter.set_designer(order.external_order_id, target_designer_opt)
            )
            if not designer_result.success:
                # Never hide it: the status is still written below, but the request ends failed.
                designer_failure = designer_result.error_class or "UNKNOWN_OUTCOME"
            if designer_result.success:
                request.observed_designer = (
                    str(designer_result.observed_state.get("designer") or "") or None
                )
                session.add(
                    ExternalObservation(
                        order_id=order.id,
                        source="printerval.assignment_request",
                        external_id=order.external_order_id,
                        observed_state=request.observed_designer,
                        evidence={"request": {"designer": request.designer_option, "status": request.target_status}},
                    )
                )

        status_result = with_retry(
            lambda: adapter.set_status(order.external_order_id, request.target_status)
        )
        if not status_result.success:
            if designer_failure:
                message = (
                    f"Không gán được Designer {request.designer_option} và chưa xác nhận được trạng thái "
                    f"{request.target_status} trên Printerval"
                )
            elif request.observed_designer:
                message = "Designer changed but Printerval Status update was not verified"
            else:
                message = "Printerval Status update was not verified"
            return _fail(request, status_result.error_class or "UNKNOWN_OUTCOME", message, status_result.evidence)
        request.observed_status = str(status_result.observed_state.get("status") or "") or None
        # The Printerval calls above take seconds; a status sync may have saved this order meanwhile.
        # Re-read it under a row lock so the mirror below is written on its latest version (the stale
        # copy loaded at the start raised StaleDataError and left the request stuck "pending").
        session.refresh(order, with_for_update=True)
        request.lifecycle = "succeeded"
        request.error_class = None
        request.error_message = None
        request.evidence = {"request": {"designer": request.designer_option, "status": request.target_status}}
        if request.observed_designer:
            order.printerval_designer = request.observed_designer
            order.printerval_designer_synced_at = datetime.now(UTC)
        order.printerval_status = (
            request.observed_status.lower() if request.observed_status else None
        )
        order.printerval_status_synced_at = datetime.now(UTC)
        session.add(
            ExternalObservation(
                order_id=order.id,
                source="printerval.assignment_request",
                external_id=order.external_order_id,
                observed_state=request.observed_status,
                evidence=request.evidence,
            )
        )
        if designer_failure:
            # The status went through (mirrored above), the Designer did not: report the request failed.
            return _fail(
                request,
                designer_failure,
                f"Không gán được Designer {request.designer_option} trên Printerval "
                f"(trạng thái {request.target_status} đã cập nhật)",
                {"request": {"designer": request.designer_option, "status": request.target_status},
                 "designer_evidence": designer_result.evidence},
            )
        return {
            "lifecycle": request.lifecycle,
            "designer": request.observed_designer,
            "status": request.observed_status,
        }

    return run_idempotent(
        session,
        f"printerval_assignment_request:{request.id}",
        "printerval_assignment_request",
        _do,
        request_fingerprint=fingerprint,
    )


def _fail(
    request: PrintervalAssignmentRequest,
    error_class: str,
    message: str,
    evidence: dict,
) -> dict:
    request.lifecycle = "unknown_outcome" if error_class == "UNKNOWN_OUTCOME" else "failed"
    request.error_class = error_class
    request.error_message = message
    request.evidence = evidence
    return {"lifecycle": request.lifecycle, "error_class": error_class}


STUCK_AFTER = timedelta(minutes=30)


def fail_stuck_requests(session: Session, *, older_than: timedelta = STUCK_AFTER) -> int:
    """A request still "pending" long after it was queued never finished (worker stopped, crash):
    end it as failed and raise an Admin toast instead of leaving a spinner forever."""
    from app.application.printerval_alerts import record_write_failure

    cutoff = datetime.now(UTC) - older_than
    stuck = (
        session.query(PrintervalAssignmentRequest)
        .filter(PrintervalAssignmentRequest.lifecycle == "pending", PrintervalAssignmentRequest.created_at < cutoff)
        .with_for_update(skip_locked=True)
        .all()
    )
    for request in stuck:
        request.lifecycle = "failed"
        request.error_class = "UNKNOWN_OUTCOME"
        request.error_message = "Yêu cầu không chạy xong (worker dừng hoặc lỗi giữa chừng); kết quả chưa được xác nhận"
    session.commit()
    for request in stuck:
        order = session.get(Order, request.order_id)
        if order is None:
            continue
        change = " và ".join(
            part for part in (
                f"Designer thành {request.designer_option}" if request.designer_option else "",
                f"trạng thái sang {request.target_status}" if request.target_status else "",
            ) if part
        ) or "cập nhật đơn"
        record_write_failure(
            session, order, action=f"đổi {change}", error=request.error_message,
            manual=f"kiểm tra trên Printerval và đổi {change} cho đơn {order.external_order_id} nếu chưa đúng",
            error_class="UNKNOWN_OUTCOME",
        )
    return len(stuck)

