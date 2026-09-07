# Phase 3 — Crawl & Claim (C1) Design

**Status:** Approved by user 2026-09-07. **Revised 2026-09-07** after the final
whole-branch review found the original §3/§4 retry claim was wrong and a real
invariant-violation gap (a claim-failed order could reach `CLAIMED_IMPORTED` without
the site ever confirming the claim) — see the corrected §3/§4 below and the SDD
ledger's ruling for the full reasoning.

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
  3. import_claimed_orders(session, adapter)   -> scans ALL orders (any batch/cycle)
                                                   that are DISCOVERED + have a confirmed
                                                   claim; adapter.download_asset per
                                                   order; on success: OrderAsset row +
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

## 3. Why no new state or schema — and how retry is actually scoped

The state model (`app/domain/state_machine.py`) already allows `DISCOVERED ->
CLAIMED_IMPORTED` directly. An order that has been claimed on the site but whose asset
import hasn't succeeded yet simply stays at `DISCOVERED` in the DB.

**Two kinds of "not yet imported" need different treatment, and the original version of
this spec conflated them (fixed here):**

- **Crashed/interrupted** (the process died mid-`import_claimed_orders`, before that
  order's per-order operation recorded any outcome): this must resume automatically on
  the next crawl cycle — claude.md §18 requires "Batch/resume/retry idempotent." Fixed
  by making `import_claimed_orders` scan across ALL batches/cycles (not just the one a
  caller just created) and giving each order its own idempotency key
  (`import_order:<external_order_id>`) — `run_idempotent`'s existing pending-lease
  reclaim then genuinely retries a crashed order on the next cycle.
- **Confirmed failure** (`with_retry` already exhausted its attempts on
  `download_asset` for this order, and it was dead-lettered): per claude.md §11,
  "Hết retry đưa vào dead_letters kèm recovery action cho operator" — an exhausted
  retry is an operator-recovery case, NOT something the crawl job should silently
  retry forever on its own. This is correct, intended behavior, not a gap: a
  dead-lettered order's per-order operation records `{"imported": False}` and
  completes (doesn't raise), so future scans see it as already-attempted and don't
  re-download — it stays visible via `dead_letters` until an operator's recovery
  action (not yet built — a Phase 4/5 follow-up, see §7) does something about it.

This satisfies the roadmap's acceptance criterion "rerun chỉ tiếp tục phần dang dở" for
the crash-recovery case, which is the case that criterion actually describes — the
original draft of this spec incorrectly implied ordinary business-failure retries too,
which would have violated claude.md §11.

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

### `import_claimed_orders(session, adapter) -> dict`
No `batch_id` parameter — scans every `Order` at state `DISCOVERED` that also has a
confirmed claim, i.e. joins against `ExternalObservation(source="printerval")`
(written only by `claim_batch` on a *successful* `set_designer` call, never on a
dead-lettered failure). This join is what makes a claim-failed order structurally
ineligible for import — it can never reach `CLAIMED_IMPORTED` without the join
condition being satisfied, closing the gap the original spec missed (a claim-failed
order used to be indistinguishable from a claim-succeeded one by `state` alone).

Idempotency key: `f"import_order:{external_order_id}"`, one per order, not one per
batch (see §3 for why this scoping is what makes crash-recovery retry actually work).
For each eligible order: calls `adapter.download_asset(order_id)` via `with_retry`
inside that order's own `run_idempotent` call. On success (`AssetResult.success is
True`): creates an `OrderAsset` row (`source_image_ref` = the adapter's returned
`local_path`, `checksum` = the adapter's `checksum`, `storage_location` = same local
path — matches tech debt #3's "local disk for pilot" decision) inside the same
transaction as `apply_transition(session, order, OrderState.CLAIMED_IMPORTED,
actor_id=None, evidence={"source": "crawl_job"})` — both commit together or neither
does, so an order is never left with a verified asset row but the old state, or vice
versa. On failure: writes a `DeadLetter` row (`source="crawl.import_claimed_orders"`)
and leaves the order at `DISCOVERED`, permanently ineligible for silent re-download
(the per-order operation is "completed", not "pending") until an operator recovers it.
A per-order `OperationInProgressError` (another process mid-attempt on that exact
order right now) is caught and that order is skipped for this cycle, not treated as a
cycle-wide failure.

`run_crawl_cycle` (in `app/workers/crawl_tasks.py`) calls `import_claimed_orders`
**unconditionally every cycle** — not gated on the current cycle having claimed
anything new — so orders stranded by a prior cycle's crash are swept even when a
cycle discovers zero new waiting orders.

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
- `import_claimed_orders`: successful download creates OrderAsset + transitions state
  atomically; failed download dead-letters and leaves state at DISCOVERED, and does
  NOT get silently retried on the next scan (confirmed-failure case, §3); a crashed
  (never-completed) attempt DOES get retried on the next scan (pending-lease reclaim);
  a claim-failed order (no confirmed-claim observation) is never selected at all, even
  if it's sitting at DISCOVERED; already-imported orders are untouched (no duplicate
  OrderAsset rows, no duplicate transition attempt — the state machine would reject a
  repeat transition anyway since CLAIMED_IMPORTED has no self-transition).
- `discover_waiting_orders`: an adapter failure (not "zero orders", an actual error)
  goes through `with_retry` and, once exhausted, is dead-lettered and logged — not
  silently treated as "nothing new."
- Celery task wiring itself (`crawl_tasks.py`) gets a thin integration test using
  Celery's `task_always_eager` test mode with the fake adapter injected — proving the
  task calls the three functions in the right order and handles a Playwright-session
  setup failure gracefully — not a live Redis/broker test.

## 7. Out of scope / follow-ups

- Web display of new orders / exception queue: Phase 4.
- Production Celery/Redis hosting: tech debt #5, unresolved, doesn't block this phase.
- Concurrency tuning beyond "1 session/site": tech debt #4, still needs real
  measurement later.
- **New follow-up (added in the 2026-09-07 revision):** an operator-facing "recover
  this dead-lettered order" action doesn't exist yet — dead-lettered claim/import
  failures are visible (in the `dead_letters` table, and eventually its web view) but
  nothing lets an operator explicitly re-trigger a specific order's claim or import.
  Natural fit for whichever phase builds the exception-queue UI (Phase 4 shows the
  data; a later phase likely adds the recovery action itself).
