"""Poll PostgreSQL jobs and run DINO comparison on the Support machine.

The production VPS only creates jobs and sends Telegram notifications. This
worker is the process that owns the Hugging Face model and the image-comparison
runtime. It claims one job at a time with PostgreSQL row locking, so it is safe
to run one or more workers against the same database.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
from backend.postgres_compare import run_comparison
from psycopg.types.json import Jsonb

logger = logging.getLogger("support_compare.local_worker")

JOB_TABLE = "support_compare_image.comparison_jobs"


@dataclass(frozen=True)
class ComparisonJob:
    id: uuid.UUID
    source_kind: str
    platform_id: uuid.UUID
    requested_count: int
    worker_id: str


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str
    model_name: str
    model_version: str | None
    embedding_dim: int
    embedding_batch_size: int
    top_k: int
    fetch_timeout: float
    scan_limit: int | None
    poll_seconds: float
    stale_after_seconds: int
    worker_id: str


def _database_url(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, str(default)))


def _optional_env_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


def _claim_next_job(
    connection: psycopg.Connection,
    *,
    worker_id: str,
    stale_after_seconds: int,
) -> ComparisonJob | None:
    row = connection.execute(
        f"""
        SELECT id, source_kind, platform_id, requested_count
        FROM {JOB_TABLE}
        WHERE status = 'queued'
           OR (
                status = 'running'
                AND (
                    heartbeat_at IS NULL
                    OR heartbeat_at < now() - (%s * interval '1 second')
                )
           )
        ORDER BY created_at ASC, id ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
        """,
        (stale_after_seconds,),
    ).fetchone()
    if row is None:
        connection.rollback()
        return None

    connection.execute(
        f"""
        UPDATE {JOB_TABLE}
        SET status = 'running', worker_id = %s, claimed_at = now(),
            started_at = now(), heartbeat_at = now(), finished_at = NULL,
            notification_sent_at = NULL, last_error = NULL
        WHERE id = %s
        """,
        (worker_id, row[0]),
    )
    connection.commit()
    return ComparisonJob(
        id=uuid.UUID(str(row[0])),
        source_kind=str(row[1]),
        platform_id=uuid.UUID(str(row[2])),
        requested_count=int(row[3]),
        worker_id=worker_id,
    )


def _mark_completed(connection: psycopg.Connection, job: ComparisonJob, summary: dict[str, Any]) -> None:
    run_id = summary.get("run_id")
    connection.execute(
        f"""
        UPDATE {JOB_TABLE}
        SET status = 'completed', run_id = %s, model_version = %s,
            processed_count = %s, duplicate_count = %s, error_count = %s,
            summary = %s, last_error = NULL, finished_at = now(), heartbeat_at = now()
        WHERE id = %s AND status = 'running' AND worker_id = %s
        """,
        (
            uuid.UUID(str(run_id)) if run_id else None,
            summary.get("model_version"),
            int(summary.get("processed_count", 0)),
            int(summary.get("duplicate_count", 0)),
            int(summary.get("error_count", 0)),
            Jsonb(summary),
            job.id,
            job.worker_id,
        ),
    )
    connection.commit()


def _mark_failed(connection: psycopg.Connection, job: ComparisonJob, error: Exception) -> None:
    message = f"{type(error).__name__}: {error}"[:2000]
    connection.execute(
        f"""
        UPDATE {JOB_TABLE}
        SET status = 'failed', last_error = %s,
            summary = %s, finished_at = now(), heartbeat_at = now()
        WHERE id = %s AND status = 'running' AND worker_id = %s
        """,
        (
            message,
            Jsonb({"error_type": type(error).__name__}),
            job.id,
            job.worker_id,
        ),
    )
    connection.commit()


def _run_job(config: WorkerConfig, job: ComparisonJob) -> dict[str, Any]:
    if job.source_kind != "support_unchecked":
        raise ValueError(f"Unsupported local comparison source: {job.source_kind}")
    return run_comparison(
        config.database_url,
        source_kind=job.source_kind,
        model_name=config.model_name,
        model_version=config.model_version,
        embedding_dim=config.embedding_dim,
        platform_id=job.platform_id,
        limit=config.scan_limit,
        top_k=config.top_k,
        embedding_batch_size=config.embedding_batch_size,
        fetch_timeout=config.fetch_timeout,
        promote_new_images=True,
    )


def run_worker(config: WorkerConfig, *, once: bool = False) -> int:
    database_url = _database_url(config.database_url)
    while True:
        try:
            with psycopg.connect(database_url) as connection:
                job = _claim_next_job(
                    connection,
                    worker_id=config.worker_id,
                    stale_after_seconds=config.stale_after_seconds,
                )
        except Exception:
            logger.exception("cannot claim a comparison job")
            if once:
                return 1
            time.sleep(config.poll_seconds)
            continue

        if job is None:
            if once:
                return 0
            time.sleep(config.poll_seconds)
            continue

        logger.info(
            "claimed comparison job=%s platform=%s requested=%s",
            job.id,
            job.platform_id,
            job.requested_count,
        )
        try:
            summary = _run_job(config, job)
        except Exception as exc:
            logger.exception("comparison job %s failed", job.id)
            try:
                with psycopg.connect(database_url) as connection:
                    _mark_failed(connection, job, exc)
            except Exception:
                logger.exception("cannot mark comparison job %s failed", job.id)
            if once:
                return 1
            continue

        try:
            with psycopg.connect(database_url) as connection:
                _mark_completed(connection, job, summary)
        except Exception:
            logger.exception("cannot mark comparison job %s completed", job.id)
            if once:
                return 1
        else:
            logger.info("completed comparison job=%s summary=%s", job.id, summary)
        if once:
            return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Support image comparison jobs on the local ML machine")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--model", default=os.environ.get("EMBEDDING_MODEL_NAME", "facebook/dinov2-base"))
    parser.add_argument("--model-version", default=os.environ.get("MODEL_VERSION"))
    parser.add_argument("--embedding-dim", type=int, default=_env_int("EMBEDDING_DIM", 768))
    parser.add_argument("--batch-size", type=int, default=_env_int("EMBEDDING_BATCH_SIZE", 16))
    parser.add_argument("--top-k", type=int, default=_env_int("TOP_K_CANDIDATES", 5))
    parser.add_argument("--timeout", type=float, default=_env_float("IMAGE_FETCH_TIMEOUT_SECONDS", 30.0))
    parser.add_argument("--scan-limit", type=int, default=_optional_env_int("SUPPORT_COMPARE_SCAN_LIMIT"))
    parser.add_argument("--poll-seconds", type=float, default=_env_float("SUPPORT_COMPARE_POLL_SECONDS", 10.0))
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=_env_int("SUPPORT_COMPARE_JOB_STALE_SECONDS", 86400),
    )
    parser.add_argument("--worker-id", default=os.environ.get("SUPPORT_COMPARE_WORKER_ID"))
    parser.add_argument("--once", action="store_true", help="claim at most one job, then exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    if not args.database_url:
        print("ERROR: DATABASE_URL is required")
        return 2
    if args.scan_limit is not None and args.scan_limit <= 0:
        print("ERROR: --scan-limit must be positive")
        return 2
    config = WorkerConfig(
        database_url=args.database_url,
        model_name=args.model,
        model_version=args.model_version,
        embedding_dim=args.embedding_dim,
        embedding_batch_size=args.batch_size,
        top_k=args.top_k,
        fetch_timeout=args.timeout,
        scan_limit=args.scan_limit,
        poll_seconds=args.poll_seconds,
        stale_after_seconds=args.stale_after_seconds,
        worker_id=args.worker_id or f"{socket.gethostname()}:{os.getpid()}",
    )
    return run_worker(config, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
