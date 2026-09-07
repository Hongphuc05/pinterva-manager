from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.adapters.db.session import SessionLocal
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval.interface import NTTH_DESIGNER_OPTION, PrintervalAdapter
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.application.crawl import claim_batch, discover_waiting_orders, import_claimed_orders
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_crawl_cycle(session: Session, adapter: PrintervalAdapter, limit: int = 40) -> dict:
    """The pure crawl-cycle logic: discover -> claim -> import, in order. Takes an
    already-open session/adapter so it's directly unit-testable with a fake adapter and
    the test DB session — no Celery or Playwright involved here.
    """
    new_order_ids = discover_waiting_orders(session, adapter, limit=limit)
    if new_order_ids:
        claim_result = claim_batch(session, adapter, new_order_ids, owner=NTTH_DESIGNER_OPTION)
        claimed_count = len(claim_result["claimed"])
        failed_claim_count = len(claim_result["failed"])
    else:
        claimed_count = 0
        failed_claim_count = 0

    import_result = import_claimed_orders(session, adapter)

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
        session_cm = playwright_session()
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
