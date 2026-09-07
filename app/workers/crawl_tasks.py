from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.adapters.db.session import SessionLocal
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval.interface import PrintervalAdapter
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.application.crawl import claim_batch, discover_waiting_orders, import_claimed_batch
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_crawl_cycle(session: Session, adapter: PrintervalAdapter, limit: int = 40) -> dict:
    """The pure crawl-cycle logic: discover -> claim -> import, in order. Takes an
    already-open session/adapter so it's directly unit-testable with a fake adapter and
    the test DB session — no Celery or Playwright involved here.
    """
    new_order_ids = discover_waiting_orders(session, adapter, limit=limit)
    if not new_order_ids:
        return {
            "discovered": 0,
            "claimed": 0,
            "failed_claim": 0,
            "imported": 0,
            "failed_import": 0,
        }

    claim_result = claim_batch(session, adapter, new_order_ids, owner="ntth")
    import_result = (
        import_claimed_batch(session, adapter, claim_result["batch_id"])
        if claim_result["claimed"]
        else {"imported": [], "failed": []}
    )
    return {
        "discovered": len(new_order_ids),
        "claimed": len(claim_result["claimed"]),
        "failed_claim": len(claim_result["failed"]),
        "imported": len(import_result["imported"]),
        "failed_import": len(import_result["failed"]),
    }


@celery_app.task(name="app.workers.crawl_tasks.crawl_and_claim")
def crawl_and_claim() -> None:
    """Celery Beat entry point: owns one Playwright session and one DB session for the
    whole cycle (claude.md tech debt #4 — 1 session/site, no persistent browser daemon).
    If the Playwright session itself fails to open (e.g. Cloudflare/login not ready),
    log and return without touching the DB — no partial batch from a browser that never
    opened.
    """
    try:
        with playwright_session() as page:
            adapter = PlaywrightPrintervalAdapter(page=page)
            session = SessionLocal()
            try:
                summary = run_crawl_cycle(session, adapter)
                logger.info("crawl_and_claim cycle summary: %s", summary)
            finally:
                session.close()
    except Exception:
        # ponytail: alembic/env.py's fileConfig (disable_existing_loggers=True, run by
        # the test suite's `engine` fixture) can flip this already-created logger's
        # `.disabled` to True mid-process. Reset defensively so this alert — the one
        # signal an operator gets that a whole crawl cycle was skipped — always fires.
        # Upgrade path: set disable_existing_loggers=False in alembic/env.py if this
        # ever needs generalizing beyond this one logger.
        logger.disabled = False
        logger.exception("crawl_and_claim: Playwright session failed to open, skipping this cycle")
