from __future__ import annotations

import argparse
import json
import logging
import sys
from uuid import UUID

from pydantic import ValidationError

from .config import CrawlConfigurationError, get_settings
from .crawler import CrawlOptions, dry_run, run_crawl
from .db import build_session_factory
from .normalizer import TARGET_STATUSES
from .printerval_client import PrintervalApiError, PrintervalClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-time read-only Printerval historical preview backfill"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dry = subparsers.add_parser("dry-run", help="read Printerval and print counts; no database writes")
    _add_common_options(dry)

    crawl = subparsers.add_parser("crawl", help="write a bounded pilot or explicit full run")
    _add_common_options(crawl)
    crawl.add_argument("--limit", type=_positive_int, help="maximum rows before stopping at a page boundary")
    crawl.add_argument(
        "--full-run",
        action="store_true",
        help="enable the unbounded four-status backfill; requires --confirm",
    )
    crawl.add_argument(
        "--confirm",
        action="store_true",
        help="confirm that this command writes the production PostgreSQL schema",
    )

    resume = subparsers.add_parser("resume", help="resume a stopped or failed run")
    _add_common_options(resume)
    resume.add_argument("--run-id", required=True, type=UUID)
    resume.add_argument("--confirm", action="store_true")

    return parser


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--status",
        action="append",
        choices=TARGET_STATUSES,
        dest="statuses",
        help="repeat to select statuses; default: done, confirm, review, fix",
    )
    parser.add_argument("--page-size", type=_page_size, default=None)
    parser.add_argument("--delay", type=_nonnegative_float, default=None, help="seconds between pages")
    parser.add_argument("--max-retries", type=_nonnegative_int, default=None)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _page_size(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 100:
        raise argparse.ArgumentTypeError("must be between 1 and 100")
    return parsed


def _nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must not be negative")
    return parsed


def _options(args: argparse.Namespace, *, limit: int | None = None) -> CrawlOptions:
    settings = get_settings()
    statuses = tuple(args.statuses or TARGET_STATUSES)
    return CrawlOptions(
        team_outsource=settings.printerval_team_outsource,
        page_size=args.page_size or settings.printerval_page_size,
        request_delay_seconds=(
            settings.printerval_request_delay_seconds if args.delay is None else args.delay
        ),
        max_retries=(settings.printerval_max_retries if args.max_retries is None else args.max_retries),
        statuses=statuses,
        limit=limit,
    )


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    try:
        settings = get_settings()
        if args.command == "crawl":
            settings.validate_database_url()
            if not args.full_run and args.limit is None:
                raise CrawlConfigurationError(
                    "crawl requires --limit for a pilot or --full-run for the complete backfill"
                )
            if args.full_run and not args.confirm:
                raise CrawlConfigurationError("full-run requires --confirm")
            if not args.full_run and not args.confirm:
                raise CrawlConfigurationError("crawl writes PostgreSQL; pass --confirm")
            limit = None if args.full_run else args.limit
            mode = "full_run" if args.full_run else "pilot"
            options = _options(args, limit=limit)
            with PrintervalClient(settings) as client:
                run = run_crawl(
                    build_session_factory(settings.database_url),
                    client,
                    options,
                    mode=mode,
                )
            _print_json(_run_summary(run))
            return 0 if run.run_status == "completed" else 2

        if args.command == "resume":
            settings.validate_database_url()
            if not args.confirm:
                raise CrawlConfigurationError("resume writes PostgreSQL; pass --confirm")
            options = _options(args)
            with PrintervalClient(settings) as client:
                run = run_crawl(
                    build_session_factory(settings.database_url),
                    client,
                    options,
                    mode="resume",
                    run_id=args.run_id,
                )
            _print_json(_run_summary(run))
            return 0 if run.run_status == "completed" else 2

        options = _options(args)
        with PrintervalClient(settings) as client:
            _print_json(dry_run(client, options))
        return 0
    except (CrawlConfigurationError, PrintervalApiError, ValidationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _run_summary(run) -> dict[str, object]:
    return {
        "run_id": str(run.id),
        "run_status": run.run_status,
        "mode": run.mode,
        "discovered_count": run.discovered_count,
        "stored_count": run.stored_count,
        "preview_missing_count": run.preview_missing_count,
        "malformed_count": run.malformed_count,
        "error_count": run.error_count,
        "status_counts": run.status_counts,
        "last_status": run.last_status,
        "last_page_id": run.last_page_id,
    }


if __name__ == "__main__":
    raise SystemExit(main())
