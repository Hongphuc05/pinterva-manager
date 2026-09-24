"""One-off backfill of ``support_compare_image.historical_jobs.custom_config``.

The pool's 89k historical jobs were crawled without their custom configuration. This reads
them back from Printerval (read-only, same ``design-job/find`` rows the web crawl uses) and
stores the configuration next to each pool entry so the duplicate Telegram message can show it.

Run once inside the API container::

    python -m app.application.historical_config_backfill            # everything
    python -m app.application.historical_config_backfill --max-pages 2 --dry-run   # try it
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.adapters.errors import ErrorClass
from app.adapters.printerval.api_client import PrintervalApiClient, PrintervalApiError
from app.adapters.printerval.row_mapper import extract_custom_config, parse_external_order_id

logger = logging.getLogger(__name__)

# The statuses the historical pool was crawled from.
HISTORICAL_STATUSES = ("done", "confirm", "review", "fix")

_UPDATE = text(
    """
    UPDATE support_compare_image.historical_jobs
    SET custom_config = CAST(:config AS jsonb), custom_config_synced_at = now()
    WHERE source_system = 'printerval' AND external_order_id = :code
    """
)


def _fetch_with_retry(fetch: Callable[[], Any], *, max_retries: int, sleep: Callable[[float], None]) -> Any:
    for attempt in range(max_retries + 1):
        try:
            return fetch()
        except PrintervalApiError as exc:
            if exc.error_class == ErrorClass.AUTH or not exc.retryable or attempt == max_retries:
                raise
            delay = min(60.0, 2.0 * 2**attempt)
            logger.warning("retryable Printerval error (%s); retry %s in %.0fs", exc, attempt + 1, delay)
            sleep(delay)
    raise AssertionError("unreachable")


def backfill(
    session: Session,
    client: PrintervalApiClient,
    *,
    statuses: Sequence[str] = HISTORICAL_STATUSES,
    page_size: int = 100,
    max_pages: int | None = None,
    delay_seconds: float = 0.25,
    max_retries: int = 5,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] = print,
) -> dict[str, int]:
    """Page through ``statuses`` and store each row's configuration. Idempotent."""
    stats = {"pages": 0, "rows": 0, "with_config": 0}
    for status in statuses:
        page_id = 0
        while max_pages is None or page_id < max_pages:
            page = _fetch_with_retry(
                lambda s=status, p=page_id: client.discover_page(status=s, page_size=page_size, page_id=p),
                max_retries=max_retries,
                sleep=sleep,
            )
            if not page.orders:
                break
            updates = []
            for row in page.orders:
                code = parse_external_order_id(row)
                if not code:
                    continue
                config = extract_custom_config(row)
                updates.append({"code": code, "config": json.dumps(config, ensure_ascii=False) if config else None})
                stats["with_config"] += 1 if config else 0
            stats["rows"] += len(updates)
            stats["pages"] += 1
            if updates and not dry_run:
                session.execute(_UPDATE, updates)
                session.commit()
            progress(f"{status}: page {page_id} rows={len(page.orders)} total={stats['rows']} with_config={stats['with_config']}")
            page_id += 1
            sleep(delay_seconds)
    return stats


def _main() -> int:
    from app.adapters.db.models import Platform
    from app.adapters.db.session import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platform-id", help="platform whose Printerval account to use (default: the one matching the pool's team)")
    parser.add_argument("--max-pages", type=int, help="pages per status (for a trial run)")
    parser.add_argument("--dry-run", action="store_true", help="read from Printerval but write nothing")
    args = parser.parse_args()

    session = SessionLocal()
    teams = {
        row[0]
        for row in session.execute(
            text("SELECT DISTINCT team_outsource FROM support_compare_image.historical_jobs WHERE source_system = 'printerval'")
        )
    }
    query = session.query(Platform).filter(Platform.team_outsource.in_(teams))
    if args.platform_id:
        query = query.filter(Platform.id == args.platform_id)
    platforms = query.all()
    if len(platforms) != 1:
        print(f"Expected exactly one platform for team(s) {sorted(teams)}, found {len(platforms)}; use --platform-id")
        return 2
    platform = platforms[0]
    print(f"Platform {platform.name} (team {platform.team_outsource}); dry_run={args.dry_run}")

    with PrintervalApiClient(
        base_url="https://printerval.com",
        username=platform.account_username,
        password=platform.account_password,
        team_outsource=platform.team_outsource,
        session_cookie=platform.session_cookie,
    ) as client:
        stats = backfill(session, client, max_pages=args.max_pages, dry_run=args.dry_run)
    total, filled = session.execute(
        text(
            "SELECT count(*), count(custom_config) FROM support_compare_image.historical_jobs "
            "WHERE source_system = 'printerval'"
        )
    ).one()
    print(f"done: {stats}; pool printerval jobs={total}, with custom_config={filled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
