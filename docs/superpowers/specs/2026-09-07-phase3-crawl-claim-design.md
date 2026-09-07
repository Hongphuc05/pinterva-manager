# Phase 3 — Crawl & Claim (C1) Design

**Status:** Approved by user 2026-09-07.

## 1. Scope

Implement C1 per claude.md §3 and roadmap.md's Phase 3: a periodic background job that
discovers `waiting` 2D orders on Printerval, claims them (`ntth`), downloads and verifies
their asset, and persists them into PostgreSQL — with no Sheet intake step, per claude.md
§2 invariant #2.

**Explicitly out of scope for this phase** (decided with the user):
- No web UI. The generic order list and exception queue that Phase 4 (web dashboard
  skeleton) builds will show these orders for free, since a crawled order is just an
  `Order` row in `DISCOVERED`/`CLAIMED_IMPORTED`/`EXCEPTION` state — nothing Phase-3-
  specific needs displaying. Building a throwaway UI now would be replaced wholesale by
  Phase 4's real layout.
- No production task-queue infrastructure decision (tech debt #5 stays open) — this
  phase only needs Celery+Redis to run locally/on a single host for pilot, matching
  claude.md §16's "V1 không có LLM nên không cần hạ tầng đặc biệt."

## 2. Architecture

```
Celery Beat (every CRAWL_INTERVAL_SECONDS, default 300)
        │
        ▼
crawl_and_claim task (app/workers/crawl_tasks.py)
        │  opens ONE playwright_session() for the whole cycle (1 session/site limit,
        │  tech debt #4), closes it at the end — no persistent browser daemon
        ▼
app/application/crawl.py
  1. discover_waiting_orders(adapter, limit)   -> new external_order_ids not in DB yet
  2. claim_batch(session, adapter, order_ids)  -> Batch + Order(DISCOVERED) rows,
                                                   adapter.set_designer("ntth") per order
  3. import_claimed_batch(session, adapter, batch_id)
                                                -> adapter.download_asset per order still
                                                   missing a verified OrderAsset;
                                                   on success: OrderAsset row +
                                                   apply_transition(DISCOVERED -> CLAIMED_IMPORTED)
        │
        ▼
PostgreSQL (orders, batches, order_assets, external_observations, operations,
            workflow_events, dead_letters — all already exist from Phase 1)
```

Each of the 3 application functions is wrapped in `run_idempotent` (already exists,
`app/application/operations.py`) with a deterministic idempotency key derived from the
batch/order id and the function name, so a crashed/retried Celery task resumes rather
than redoing already-completed work.

## 3. Why no new state or schema

The state model (`app/domain/state_machine.py`) already allows `DISCOVERED ->
CLAIMED_IMPORTED` directly. An order that has been claimed on the site but whose asset
import hasn't succeeded yet simply stays at `DISCOVERED` in the DB — the next crawl
cycle's `import_claimed_batch` naturally retries it (any order in the batch missing an
`OrderAsset` row is still "pending import"). This satisfies the roadmap's acceptance
criterion "rerun chỉ tiếp tục phần dang dở" with zero new state or columns.

`Order.external_order_id`'s existing unique constraint (Phase 1) is the dedupe
mechanism: `discover_waiting_orders` filters out any external ID already present in the
DB before returning "new" orders, so re-discovering an order still sitting in `waiting`
across multiple crawl cycles (before it's claimed, or while import retries) never
creates a duplicate row.

## 4. Data flow per function

### `discover_waiting_orders(adapter, limit) -> list[str]`
Calls `adapter.discover_orders(status="Waiting", job_type="2D", limit=limit)`. Queries
existing `Order.external_order_id` values and returns only the external IDs not already
present. Pure read — no DB writes, no idempotency key needed (safe to call repeatedly).

### `claim_batch(session, adapter, order_ids, owner="ntth") -> BatchResult`
Idempotency key: `f"claim_batch:{sorted(order_ids)}"` (deterministic from input). Creates
one `Batch` row (`source="printerval_crawl"`, `owner="ntth"`, `count=len(order_ids)`).
For each order_id: creates an `Order` row (state=`DISCOVERED`, linked to the batch) if
one doesn't already exist for that external_order_id (defensive — `discover_waiting_orders`
should have already filtered, but a crash between discover and claim makes this
re-entrant-safe); calls `adapter.set_designer(order_id, owner)` via `with_retry`; on
success writes an `ExternalObservation` row (`source="printerval"`, observed state
`"waiting"` pre-claim is not re-observed here — the *action* being recorded is the claim
itself, so `observed_state` is whatever the adapter's `WriteResult.observed_state`
reports, typically the designer now assigned); on failure (adapter returns
`success=False` and non-retryable, or retries exhausted) writes a `DeadLetter` row
(`source="crawl.claim_batch"`, `payload={"order_id": ..., "batch_id": ...}`,
`error_class` from the adapter result) and leaves that order's DB row exactly as
created (`DISCOVERED`, unclaimed on-site) — the batch's other orders still proceed
independently; one order's claim failure never aborts the whole batch (partial success
tracked in `BatchResult.claimed`/`failed` lists).

### `import_claimed_batch(session, adapter, batch_id) -> BatchResult`
Idempotency key: `f"import_claimed_batch:{batch_id}"`. Queries the batch's `Order` rows
still at state `DISCOVERED` (these are "claimed but not yet imported" — the design
decision in §3). For each: calls `adapter.download_asset(order_id)` via `with_retry`.
On success (`AssetResult.success is True`): creates an `OrderAsset` row
(`source_image_ref` = the adapter's returned `local_path`, `checksum` = the adapter's
`checksum`, `storage_location` = same local path — matches tech debt #3's "local disk
for pilot" decision) inside the same transaction as
`apply_transition(session, order, OrderState.CLAIMED_IMPORTED, actor_id=None,
evidence={"source": "crawl_job"})` — both commit together or neither does, so an order
is never left with a verified asset row but the old state, or vice versa. On failure:
writes a `DeadLetter` row (`source="crawl.import_claimed_batch"`) and leaves the order
at `DISCOVERED` for the next cycle to retry — never partially transitions.

## 5. Celery task

`app/workers/celery_app.py`: a `Celery` instance, broker and result backend both
`REDIS_URL` (new setting in `app/config.py`, default
`redis://localhost:6379/0`), `beat_schedule` registering `crawl_and_claim` at
`CRAWL_INTERVAL_SECONDS` (new setting, default `300`).

`app/workers/crawl_tasks.py`: the `crawl_and_claim` task. Opens a DB session
(`SessionLocal()`, already exists) and a Playwright session
(`playwright_session()`, already exists) for the task's duration; builds a
`PlaywrightPrintervalAdapter(page)`; calls the three application functions in
sequence (discover -> claim -> import), logging a structured summary (counts:
discovered/claimed/failed_claim/imported/failed_import) at the end — matching claude.md
§14's observability requirement (`correlation_id`, `batch_id`, `order_id`, etc. per
event, at minimum a per-run summary log for this phase; full structured tracing is a
later-phase concern once there's a log aggregation story). If Playwright session setup
itself fails (e.g., Cloudflare/login issue), the task logs and exits without touching
the DB — no partial batch is ever created from a browser that never opened.

## 6. Testing

All automated tests use `FakePrintervalAdapter` (Phase 2) and a real test DB session
(the pattern already established in `tests/test_operations.py`/`tests/test_state_machine.py`)
— no Celery, no Redis, no real Playwright/site access in pytest, per claude.md §13.

- `discover_waiting_orders`: returns only orders not already in the DB; empty when
  everything's already known.
- `claim_batch`: creates Batch + Order rows; on a per-order adapter failure, that order
  is dead-lettered and the rest of the batch still succeeds; re-running with the same
  order_ids (crash-resume) doesn't create duplicate Order/Batch rows (idempotency key
  reuse returns the cached result).
- `import_claimed_batch`: successful download creates OrderAsset + transitions state
  atomically; failed download dead-letters and leaves state at DISCOVERED; re-running
  only retries orders still missing an OrderAsset (already-imported orders are
  untouched — no duplicate OrderAsset rows, no duplicate transition attempt, which the
  state machine would reject anyway since CLAIMED_IMPORTED has no self-transition).
- Celery task wiring itself (`crawl_tasks.py`) gets a thin integration test using
  Celery's `task_always_eager` test mode with the fake adapter injected — proving the
  task calls the three functions in the right order and handles a Playwright-session
  setup failure gracefully — not a live Redis/broker test.

## 7. Out of scope / follow-ups

- Web display of new orders / exception queue: Phase 4.
- Production Celery/Redis hosting: tech debt #5, unresolved, doesn't block this phase.
- Concurrency tuning beyond "1 session/site": tech debt #4, still needs real
  measurement later.
