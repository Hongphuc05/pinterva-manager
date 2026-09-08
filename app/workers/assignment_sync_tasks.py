from __future__ import annotations

import logging
import uuid

from app.adapters.db.models import Order, Platform, PrintervalAssignmentRequest, User
from app.adapters.db.session import SessionLocal
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.application.assignment_sync import sync_assignment_to_printerval
from app.application.printerval_assignment_requests import execute_request
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.assignment_sync_tasks.sync_printerval_assignment_request")
def sync_printerval_assignment_request(request_id: str) -> None:
    """Run one explicit per-order Designer/Status request for its own platform."""
    session = SessionLocal()
    try:
        request = session.get(PrintervalAssignmentRequest, uuid.UUID(request_id))
        if request is None:
            logger.error("Printerval assignment request %s not found", request_id)
            return
        platform = session.get(Platform, request.platform_id)
        if platform is None or not platform.account_password:
            request.lifecycle = "failed"
            request.error_class = "AUTH"
            request.error_message = "Platform credentials are unavailable"
            session.commit()
            return
        account_slug = platform.account_username.replace("@", "_").replace(".", "_")
        profile_dir = "chrome-profile-" + account_slug
        # Chrome real is required by the known Cloudflare behaviour for write flows.
        with playwright_session(profile_dir=profile_dir, headless=True) as page:
            adapter = PlaywrightPrintervalAdapter(
                page=page,
                crawl_username=platform.account_username,
                crawl_password=platform.account_password,
            )
            execute_request(session, adapter, request)
    except Exception:
        logger.exception("Printerval assignment request %s crashed", request_id)
    finally:
        session.close()


@celery_app.task(name="app.workers.assignment_sync_tasks.sync_assignment_to_printerval_task")
def sync_assignment_to_printerval_task(order_id: str, designer_id: str) -> None:
    """Triggered right after an internal assignment is created (orders_api.py), not on
    a schedule — one Playwright session per call, same shape as crawl_tasks.crawl_and_claim
    (claude.md tech debt #4: 1 session/site). A failure here is dead-lettered by
    sync_assignment_to_printerval itself (visible on Kanban's existing dead_letters-based
    alert badge) — this task only handles failures *before* that point (order/designer
    gone, platform has no credentials, browser never opened).
    """
    logger.disabled = False  # see crawl_tasks.crawl_and_claim's identical ponytail note
    session = SessionLocal()
    try:
        order = session.get(Order, uuid.UUID(order_id))
        designer = session.get(User, uuid.UUID(designer_id))
        if order is None or designer is None:
            logger.error(
                "sync_assignment_to_printerval_task: order %s or designer %s not found",
                order_id, designer_id,
            )
            return
        if not designer.printerval_designer_option:
            # Not an error — this designer just isn't registered on Printerval.
            return

        platform = session.get(Platform, order.platform_id) if order.platform_id else None
        if platform is None or not platform.account_password:
            logger.error(
                "sync_assignment_to_printerval_task: platform credentials missing for order %s",
                order.external_order_id,
            )
            return

        clean_slug = platform.account_username.replace("@", "_").replace(".", "_").replace("+", "_")
        profile_dir = f"chrome-profile-{clean_slug}"
        try:
            session_cm = playwright_session(profile_dir=profile_dir, headless=True)
            page = session_cm.__enter__()
        except Exception:
            logger.exception(
                "sync_assignment_to_printerval_task: Playwright session failed to open for order %s",
                order.external_order_id,
            )
            return

        try:
            adapter = PlaywrightPrintervalAdapter(
                page=page,
                crawl_username=platform.account_username,
                crawl_password=platform.account_password,
            )
            try:
                result = sync_assignment_to_printerval(session, adapter, order, designer)
                logger.info(
                    "sync_assignment_to_printerval_task result for %s: %s",
                    order.external_order_id, result,
                )
            except Exception:
                logger.exception(
                    "sync_assignment_to_printerval_task: unexpected exception mid-run for order %s",
                    order.external_order_id,
                )
        finally:
            session_cm.__exit__(None, None, None)
    finally:
        session.close()
