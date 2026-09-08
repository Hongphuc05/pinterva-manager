from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.adapters.db.session import SessionLocal
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval.interface import ALL_JOB_TYPES, NTTH_DESIGNER_OPTION, PrintervalAdapter
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.application.crawl import (
    claim_batch,
    discover_waiting_orders_with_summaries,
    export_platform_orders_csv,
    find_unclaimed_order_ids,
    import_claimed_orders,
    retry_failed_claims,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_crawl_cycle(
    session: Session,
    adapter: PrintervalAdapter,
    limit: int = 40,
    platform_id: uuid.UUID | None = None,
    job_type: str = ALL_JOB_TYPES,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    """The pure crawl-cycle logic: discover -> claim -> import, in order. Takes an
    already-open session/adapter so it's directly unit-testable with a fake adapter and
    the test DB session — no Celery or Playwright involved here.
    """
    new_order_ids, summaries = discover_waiting_orders_with_summaries(
        session,
        adapter,
        limit=limit,
        platform_id=platform_id,
        job_type=job_type,
        date_from=date_from,
        date_to=date_to,
    )
    claimed_count = 0
    failed_claim_count = 0
    if new_order_ids:
        claim_result = claim_batch(
            session,
            adapter,
            new_order_ids,
            owner=NTTH_DESIGNER_OPTION,
            order_summaries=summaries,
            platform_id=platform_id,
        )
        claimed_count += len(claim_result["claimed"])
        failed_claim_count += len(claim_result["failed"])

    # Retry orders a prior claim_batch dead-lettered — they already have an Order row
    # so discover_waiting_orders_with_summaries's "new" filter will never surface them
    # again on its own. Goes through retry_failed_claims, NOT claim_batch: this same
    # still-unclaimed set is resubmitted every cycle nothing new is discovered, and
    # claim_batch's idempotency key (a hash of the exact order_ids) would otherwise
    # cache the very first failure forever, silently never retrying against the site
    # again (see retry_failed_claims's docstring).
    retry_ids = [oid for oid in find_unclaimed_order_ids(session, platform_id) if oid not in new_order_ids]
    if retry_ids:
        retry_result = retry_failed_claims(
            session, adapter, retry_ids, owner=NTTH_DESIGNER_OPTION, platform_id=platform_id
        )
        claimed_count += len(retry_result["claimed"])
        failed_claim_count += len(retry_result["failed"])

    import_result = import_claimed_orders(session, adapter)

    # One clean, DB-driven snapshot per platform — replaces the old per-row CSV append
    # (which duplicated a row on every retry/poll and had no platform isolation).
    export_platform_orders_csv(session, platform_id)

    return {
        "discovered": len(new_order_ids),
        "claimed": claimed_count,
        "failed_claim": failed_claim_count,
        "imported": len(import_result["imported"]),
        "failed_import": len(import_result["failed"]),
    }


@celery_app.task(name="app.workers.crawl_tasks.crawl_and_claim")
def crawl_and_claim() -> None:
    """Celery Beat entry point: owns one Playwright session and one DB session for the
    whole cycle (claude.md tech debt #4 — 1 session/site, no persistent browser daemon).
    If the Playwright session itself fails to open (e.g. Cloudflare/login not ready),
    log and return without touching the DB — no partial batch from a browser that never
    opened. A failure inside the cycle itself (after the session opened) is logged
    distinctly, since by that point real DB writes may already be committed.
    """
    # ponytail: alembic/env.py's fileConfig (disable_existing_loggers=True, run by the
    # test suite's `engine` fixture) can flip this already-created logger's `.disabled`
    # to True mid-process. Reset defensively up front so every log path below — not
    # just the failure one — always fires. Upgrade path: set
    # disable_existing_loggers=False in alembic/env.py if this ever needs generalizing
    # beyond this one logger.
    logger.disabled = False

    try:
        # Scheduled crawling must never open a visible Chrome window for operators.
        session_cm = playwright_session(headless=True)
        page = session_cm.__enter__()
    except Exception:
        logger.exception("crawl_and_claim: Playwright session failed to open, skipping this cycle")
        return

    try:
        adapter = PlaywrightPrintervalAdapter(page=page)
        session = SessionLocal()
        try:
            summary = run_crawl_cycle(session, adapter)
            logger.info("crawl_and_claim cycle summary: %s", summary)
        except Exception:
            logger.exception("crawl_and_claim: cycle raised an unexpected exception mid-run")
        finally:
            session.close()
    finally:
        session_cm.__exit__(None, None, None)
