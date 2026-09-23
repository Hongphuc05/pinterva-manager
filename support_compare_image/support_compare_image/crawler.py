from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CrawlCheckpoint, CrawlError, CrawlRun
from .normalizer import TARGET_STATUSES, NormalizedJob, RowNormalizationError, normalize_row
from .printerval_client import PrintervalApiError, PrintervalClient, PrintervalPage
from .repository import upsert_job

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CrawlOptions:
    team_outsource: str
    page_size: int = 100
    request_delay_seconds: float = 0.25
    max_retries: int = 5
    job_type: str = "all"
    statuses: tuple[str, ...] = TARGET_STATUSES
    limit: int | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _empty_status_counts(statuses: tuple[str, ...]) -> dict[str, dict[str, int]]:
    return {
        status: {"discovered": 0, "stored": 0, "preview_missing": 0, "malformed": 0}
        for status in statuses
    }


def _new_run(session: Session, options: CrawlOptions, mode: str) -> CrawlRun:
    run = CrawlRun(
        id=uuid4(),
        mode=mode,
        source_system="printerval",
        team_outsource=options.team_outsource,
        job_type=options.job_type,
        target_statuses=list(options.statuses),
        page_size=options.page_size,
        run_status="running",
        status_counts=_empty_status_counts(options.statuses),
    )
    session.add(run)
    session.flush()
    for status in options.statuses:
        session.add(CrawlCheckpoint(run_id=run.id, status=status))
    session.commit()
    return run


def _load_or_prepare_run(
    session: Session,
    options: CrawlOptions,
    mode: str,
    run_id: UUID | None,
) -> CrawlRun:
    if run_id is None:
        return _new_run(session, options, mode)

    run = session.get(CrawlRun, run_id)
    if run is None:
        raise ValueError(f"Crawl run {run_id} does not exist")
    if run.run_status == "completed":
        return run
    run.run_status = "running"
    run.last_error = None
    session.commit()
    return run


def _fetch_with_retry(
    client: PrintervalClient,
    *,
    status: str,
    page_id: int,
    page_size: int,
    max_retries: int,
    request_delay_seconds: float,
) -> PrintervalPage:
    for attempt in range(max_retries + 1):
        try:
            return client.fetch_page(status=status, page_id=page_id, page_size=page_size)
        except PrintervalApiError as exc:
            if not exc.retryable or attempt >= max_retries:
                raise
            backoff = min(60.0, max(1.0, 2**attempt))
            logger.warning(
                "Printerval page retry: status=%s page=%s attempt=%s/%s code=%s",
                status,
                page_id,
                attempt + 1,
                max_retries,
                exc.error_code,
            )
            time.sleep(backoff + request_delay_seconds)
    raise RuntimeError("unreachable retry state")


def _record_error(
    session: Session,
    *,
    run_id: UUID,
    status: str | None,
    page_id: int | None,
    code: str,
    message: str,
    source_job_id: str | None = None,
    payload_hash: str | None = None,
) -> None:
    session.add(
        CrawlError(
            run_id=run_id,
            status=status,
            page_id=page_id,
            source_job_id=source_job_id,
            error_code=code,
            message=message[:4000],
            payload_hash=payload_hash,
        )
    )


def _checkpoint_for(session: Session, run_id: UUID, status: str) -> CrawlCheckpoint:
    checkpoint = session.scalar(
        select(CrawlCheckpoint).where(
            CrawlCheckpoint.run_id == run_id,
            CrawlCheckpoint.status == status,
        )
    )
    if checkpoint is None:
        checkpoint = CrawlCheckpoint(run_id=run_id, status=status)
        session.add(checkpoint)
        session.flush()
    return checkpoint


def _update_status_count(run: CrawlRun, status: str, key: str, amount: int) -> None:
    counts = dict(run.status_counts or {})
    current = dict(counts.get(status) or {})
    current[key] = int(current.get(key, 0)) + amount
    counts[status] = current
    run.status_counts = counts


def _persist_page(
    session: Session,
    *,
    run: CrawlRun,
    checkpoint: CrawlCheckpoint,
    page: PrintervalPage,
    options: CrawlOptions,
) -> tuple[int, int, int]:
    stored = 0
    preview_missing = 0
    malformed = 0
    normalized_rows: list[NormalizedJob] = []

    for row in page.rows:
        try:
            normalized = normalize_row(
                row,
                team_outsource=options.team_outsource,
                job_type=options.job_type,
            )
        except RowNormalizationError as exc:
            malformed += 1
            _record_error(
                session,
                run_id=run.id,
                status=page.status,
                page_id=page.page_id,
                code=exc.code,
                message=str(exc),
                source_job_id=exc.source_job_id,
            )
            continue
        normalized_rows.append(normalized)

    for normalized in normalized_rows:
        upsert_job(session, normalized, run_id=run.id)
        stored += 1
        if normalized.preview_missing:
            preview_missing += 1

    checkpoint.pages_fetched += 1
    checkpoint.rows_seen += len(page.rows)
    checkpoint.rows_stored += stored
    checkpoint.preview_missing_count += preview_missing
    checkpoint.malformed_count += malformed
    checkpoint.next_page_id = page.page_id + 1
    checkpoint.api_total_count = page.total_count
    checkpoint.api_page_count = page.page_count
    checkpoint.last_error = None
    checkpoint.completed = (
        not page.rows
        or len(page.rows) < options.page_size
        or (page.page_count is not None and page.page_id + 1 >= page.page_count)
    )

    run.discovered_count += len(page.rows)
    run.stored_count += stored
    run.preview_missing_count += preview_missing
    run.malformed_count += malformed
    run.last_status = page.status
    run.last_page_id = page.page_id
    _update_status_count(run, page.status, "discovered", len(page.rows))
    _update_status_count(run, page.status, "stored", stored)
    _update_status_count(run, page.status, "preview_missing", preview_missing)
    _update_status_count(run, page.status, "malformed", malformed)
    return stored, preview_missing, malformed


def _mark_finished(session: Session, run: CrawlRun, status: str, error: str | None = None) -> None:
    run.run_status = status
    run.last_error = error
    run.finished_at = _now()
    session.commit()


def run_crawl(
    session_factory: Callable[[], Session],
    client: PrintervalClient,
    options: CrawlOptions,
    *,
    mode: str = "crawl",
    run_id: UUID | None = None,
) -> CrawlRun:
    """Run or resume a one-time crawl. Every successful page is committed atomically."""
    with session_factory() as session:
        run = _load_or_prepare_run(session, options, mode, run_id)
        if run.run_status == "completed":
            return run
        if run_id is not None:
            persisted_statuses = tuple(
                value for value in (run.target_statuses or []) if value in TARGET_STATUSES
            )
            if persisted_statuses:
                options = replace(
                    options,
                    team_outsource=run.team_outsource,
                    job_type=run.job_type,
                    page_size=run.page_size,
                    statuses=persisted_statuses,
                )

        try:
            for status in options.statuses:
                checkpoint = _checkpoint_for(session, run.id, status)
                session.commit()
                if checkpoint.completed:
                    continue

                while True:
                    if options.limit is not None and run.stored_count >= options.limit:
                        _mark_finished(session, run, "stopped")
                        return run

                    page_id = checkpoint.next_page_id
                    try:
                        page = _fetch_with_retry(
                            client,
                            status=status,
                            page_id=page_id,
                            page_size=options.page_size,
                            max_retries=options.max_retries,
                            request_delay_seconds=options.request_delay_seconds,
                        )
                    except PrintervalApiError as exc:
                        session.rollback()
                        checkpoint = _checkpoint_for(session, run.id, status)
                        checkpoint.last_error = f"{exc.error_code}: {exc}"
                        run = session.get(CrawlRun, run.id) or run
                        run.error_count += 1
                        run.last_status = status
                        run.last_page_id = page_id
                        run.last_error = f"{exc.error_code}: {exc}"
                        _record_error(
                            session,
                            run_id=run.id,
                            status=status,
                            page_id=page_id,
                            code=exc.error_code,
                            message=str(exc),
                        )
                        _mark_finished(session, run, "failed", run.last_error)
                        raise

                    try:
                        _persist_page(
                            session,
                            run=run,
                            checkpoint=checkpoint,
                            page=page,
                            options=options,
                        )
                        session.commit()
                    except Exception:
                        session.rollback()
                        failed_run = session.get(CrawlRun, run.id) or run
                        failed_run.error_count += 1
                        failed_run.last_status = status
                        failed_run.last_page_id = page_id
                        failed_run.last_error = "database error while storing page"
                        _record_error(
                            session,
                            run_id=run.id,
                            status=status,
                            page_id=page_id,
                            code="database_error",
                            message="database error while storing page; inspect server logs",
                        )
                        _mark_finished(session, failed_run, "failed", failed_run.last_error)
                        raise

                    if checkpoint.completed:
                        break
                    if options.request_delay_seconds > 0:
                        time.sleep(options.request_delay_seconds)

                checkpoint = _checkpoint_for(session, run.id, status)
                session.commit()

            _mark_finished(session, run, "completed")
            return run
        except Exception:
            # The specific error path above persists a safe message. This fallback
            # catches unexpected control-flow errors without exposing payloads.
            if session.in_transaction():
                session.rollback()
            failed_run = session.get(CrawlRun, run.id)
            if failed_run is not None and failed_run.run_status == "running":
                _mark_finished(session, failed_run, "failed", "unexpected crawler error")
            raise


def dry_run(
    client: PrintervalClient,
    options: CrawlOptions,
) -> dict[str, object]:
    """Read and count rows without opening a database session or writing anything."""
    by_status: dict[str, dict[str, int]] = defaultdict(
        lambda: {"api_rows": 0, "normalized_rows": 0, "preview_missing": 0, "malformed": 0}
    )
    api_totals: dict[str, dict[str, int | None]] = {}
    errors: list[dict[str, object]] = []
    total_normalized = 0

    for status in options.statuses:
        page_id = 0
        while True:
            if options.limit is not None and total_normalized >= options.limit:
                break
            try:
                page = _fetch_with_retry(
                    client,
                    status=status,
                    page_id=page_id,
                    page_size=options.page_size,
                    max_retries=options.max_retries,
                    request_delay_seconds=options.request_delay_seconds,
                )
            except PrintervalApiError as exc:
                errors.append({"status": status, "page_id": page_id, "code": exc.error_code})
                break

            by_status[status]["api_rows"] += len(page.rows)
            api_totals[status] = {
                "total_count": page.total_count,
                "page_count": page.page_count,
            }
            for row in page.rows:
                try:
                    normalized = normalize_row(
                        row,
                        team_outsource=options.team_outsource,
                        job_type=options.job_type,
                    )
                except RowNormalizationError as exc:
                    by_status[status]["malformed"] += 1
                    errors.append(
                        {"status": status, "page_id": page_id, "code": exc.code}
                    )
                    continue
                total_normalized += 1
                by_status[status]["normalized_rows"] += 1
                if normalized.preview_missing:
                    by_status[status]["preview_missing"] += 1

            if (
                not page.rows
                or len(page.rows) < options.page_size
                or (page.page_count is not None and page.page_id + 1 >= page.page_count)
            ):
                break
            page_id += 1
            if options.request_delay_seconds > 0:
                time.sleep(options.request_delay_seconds)

    return {
        "statuses": by_status,
        "api_totals": api_totals,
        "total_normalized_rows": total_normalized,
        "errors": errors,
    }
