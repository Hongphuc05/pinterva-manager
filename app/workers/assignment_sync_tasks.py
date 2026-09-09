from __future__ import annotations

import logging
import uuid

from app.adapters.db.models import Order, Platform, PrintervalAssignmentRequest, User
from app.adapters.db.session import SessionLocal
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval.api_adapter import PrintervalApiAdapter
from app.adapters.printerval.api_client import PrintervalApiClient
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
        if platform is None or not (platform.account_password or platform.session_cookie):
            request.lifecycle = "failed"
            request.error_class = "AUTH"
            request.error_message = "Platform credentials are unavailable"
            session.commit()
            return
        # A real browser fallback matters here specifically when a password is
        # available. Cookie-only platforms stay HTTP-only, avoiding a pointless
        # interactive login attempt with no password.
        # 2026-09-09 — a *fresh* httpx login (no persistent browser session) started
        # getting rejected with 403/AUTH after this endpoint had been hit repeatedly in
        # a short window (crawl + manual testing), even though the account/password
        # were correct — while the persistent Chrome profile (already logged in, no
        # fresh login needed per call) kept working. Without a fallback, that one
        # rejected login permanently failed the whole Designer+Status write with no
        # automatic recovery.
        clean_slug = platform.account_username.replace("@", "_").replace(".", "_").replace("+", "_")
        profile_dir = f"chrome-profile-{clean_slug}"
        fallback = None
        session_cm = None
        if platform.account_password:
            try:
                session_cm = playwright_session(profile_dir=profile_dir, headless=True)
                page = session_cm.__enter__()
                fallback = PlaywrightPrintervalAdapter(
                    page=page,
                    crawl_username=platform.account_username,
                    crawl_password=platform.account_password,
                )
            except Exception:
                logger.exception(
                    "Printerval assignment request %s: Playwright fallback failed to open, "
                    "continuing HTTP-only", request_id,
                )
                session_cm = None
        try:
            with PrintervalApiClient(
                base_url="https://printerval.com",
                username=platform.account_username,
                password=platform.account_password,
                team_outsource=platform.team_outsource,
                session_cookie=platform.session_cookie,
            ) as client:
                adapter = PrintervalApiAdapter(client, fallback_adapter=fallback, download_images=False)
                execute_request(session, adapter, request)
        finally:
            if session_cm is not None:
                session_cm.__exit__(None, None, None)
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


@celery_app.task(name="app.workers.assignment_sync_tasks.sync_order_review_to_printerval_task")
def sync_order_review_to_printerval_task(order_id: str, note_outsource: str, target_status: str = "Review") -> None:
    """Sync an order's Note Outsource (Drive link or instructions) and target status ("Review") to Printerval."""
    from datetime import UTC, datetime

    logger.disabled = False
    session = SessionLocal()
    try:
        order = session.get(Order, uuid.UUID(order_id))
        if order is None:
            logger.error("sync_order_review_to_printerval_task: order %s not found", order_id)
            return

        platform = session.get(Platform, order.platform_id) if order.platform_id else None
        if platform is None or not platform.account_password:
            logger.error(
                "sync_order_review_to_printerval_task: platform credentials missing for order %s",
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
                "sync_order_review_to_printerval_task: Playwright session failed to open for order %s",
                order.external_order_id,
            )
            return

        try:
            adapter = PlaywrightPrintervalAdapter(
                page=page,
                crawl_username=platform.account_username,
                crawl_password=platform.account_password,
            )
            # 1. Update note outsource on Printerval if text provided
            if note_outsource and note_outsource.strip():
                try:
                    res_note = adapter.attach_result_link(order.external_order_id, note_outsource.strip())
                    logger.info("attach_result_link for %s: %s", order.external_order_id, res_note)
                except Exception:
                    logger.exception("Failed attach_result_link for %s", order.external_order_id)

            # 2. Update status on Printerval
            if target_status:
                try:
                    res_status = adapter.set_status(order.external_order_id, target_status)
                    logger.info("set_status (%s) for %s: %s", target_status, order.external_order_id, res_status)
                    if res_status.success:
                        order.printerval_status = target_status.lower()
                        order.printerval_status_synced_at = datetime.now(UTC)
                        session.commit()
                except Exception:
                    logger.exception("Failed set_status for %s", order.external_order_id)
        finally:
            session_cm.__exit__(None, None, None)
    finally:
        session.close()

