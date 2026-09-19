# Order concurrency: design and implementation plan

**Status:** Phase 3 complete; Phase 4 awaits approval
**Owner:** Tacahu Ops  
**Scope:** Concurrent writes to an order, its active assignment, result submission,
Fix/QC decisions, finance actions, duplicate board actions, and Printerval sync.

## 1. Problem and goals

Several users and background workers can act on the same order at nearly the
same time. The system must never silently overwrite an important business
decision, move an order through an invalid state, notify the wrong designer, or
repeat an external Printerval/Telegram side effect.

The source of truth is PostgreSQL and the application command layer. Printerval
is an external projection/read-only observation except for explicitly queued
assignment requests.

### Goals

- Reject stale business writes with a deterministic `409 Conflict`.
- Make every state-changing action a validated, authorized domain command.
- Keep database locks short and transactional.
- Make HTTP retries and worker retries idempotent.
- Retain append-only evidence of actor, command, versions and outcome.
- Let bulk actions partially succeed while reporting each stale/rejected order.

### Non-goals for the first implementation

- Generic 10--15 minute lock when someone merely opens an order.
- Automatic field-level merge of free-text edits.
- WebSocket/SSE delivery before write correctness is complete.
- Replacing the existing workflow/state machine.

## 2. Existing foundation and gap

`Order` already has SQLAlchemy optimistic versioning (`version` mapped as
`version_id_col`). Designer task commands lock both `Assignment` and `Order`;
finance and duplicate-board commands use row locks in selected paths; operations
already provide idempotency and `WorkflowEvent` is the audit record.

The missing piece is a single API contract. Most read payloads do not expose
`version`, mutations do not consistently receive an expected version, and ORM
`StaleDataError` is not consistently turned into a safe `409` response. A number
of assignment/state/metadata endpoints also mutate orders without a uniform
lock-and-revalidate sequence.

## 3. Target invariants

1. A client cannot mutate an order based on an older order revision.
2. A command validates ownership and workflow state *after* it locks current
   rows, never only against an earlier read.
3. `Order.state`, active `Assignment`, `ResultVersion`, and its `WorkflowEvent`
   commit atomically.
4. No side effect is dispatched until its authoritative transaction commits.
5. Retrying the same command with the same idempotency key produces no duplicate
   record, notification, or external update.
6. Printerval sync never overwrites Tacahu-authoritative fields: internal state,
   internal assignment, `deadline_tacahu`, or admin/designer notes.
7. A conflict payload respects the caller's data visibility restrictions.

## 4. Concurrency contract

### Reads

All order-bearing read models return:

```json
{
  "id": "order UUID",
  "version": 12,
  "updated_at": "2026-09-19T12:00:00Z"
}
```

This includes order list/detail, My Tasks, Duplicate Board and any finance or
workload record that can initiate an order mutation.

### Mutations

Every new/converted order command accepts these fields:

```json
{
  "expected_version": 12,
  "idempotency_key": "UUID v4"
}
```

The first rollout supports optional `expected_version` only for legacy clients.
Once every shipped UI sends it, server-side enforcement becomes mandatory. The
long-term HTTP form may migrate to `If-Match`, but body fields are used first to
minimize frontend rollout risk.

### Success

```json
{
  "order_id": "order UUID",
  "version": 13,
  "updated_at": "2026-09-19T12:00:05Z",
  "state": "IN_PROGRESS"
}
```

### Conflict

```json
{
  "detail": {
    "code": "ORDER_VERSION_CONFLICT",
    "message": "Đơn đã được cập nhật bởi người khác.",
    "order_id": "order UUID",
    "expected_version": 12,
    "current_version": 13,
    "changed_fields": ["state", "assignment"],
    "current_order": {}
  }
}
```

`current_order` is built with the same role-aware sanitization as a normal read.
The client never retries the old mutation automatically.

## 5. Command execution protocol

```text
authenticate
  -> authorize
  -> validate payload and idempotency key
  -> claim/replay operation record
  -> SELECT order (+ active assignment where relevant) FOR UPDATE
  -> validate expected version
  -> revalidate state, ownership and business rules
  -> write order/assignment/result/event in one transaction
  -> commit
  -> enqueue durable external request and async notification
  -> reconcile retry/UNKNOWN_OUTCOME when an external call times out
```

Locks are held only inside this short database transaction. A browser tab never
holds a DB lock.

## 6. Ownership of data

| Data | Authority | Concurrency rule |
|---|---|---|
| Internal workflow state, assignment, Tacahu deadline, admin note | Tacahu command layer | Expected order version plus row lock |
| `printerval_status`, external designer observation | Printerval sync | System command; never overwrites internal fields |
| Result submission and QC decision | Assigned designer/QC command | Lock order and assignment; validate active ownership |
| Payment state | Admin finance command | Lock each order; per-item version validation |
| Duplicate-board position/domain | Authorized board command | Lock order and active assignment; expected version |

Initially a Printerval mirror write may still increment `Order.version`; sync
must therefore catch per-order optimistic conflicts and retry/reconcile without
aborting its batch. A later phase can introduce a separate external revision if
measurements show excessive harmless conflicts.

## 7. Endpoint conversion inventory

| Priority | Existing endpoint/group | Target command |
|---|---|---|
| P1 | `POST /assignments`, revoke, legacy assign/bulk-assign | assign, reassign, revoke assignment |
| P1 | Designer start/sub-status/result/missing-template | designer task commands with expected order revision |
| P1 | approve/reject Fix and legacy state patch | explicit workflow transition commands |
| P2 | mark/unmark paid | finance commands with per-order partial result |
| P2 | designer note, resolve missing template, deadline Tacahu, gallery | metadata commands |
| P2 | duplicate board move/domain/check status | board commands |
| P3 | Printerval status/platform assignment synchronization | system commands and reconciliation |

`PATCH /orders/{order_id}/state` is legacy. It remains temporarily for backward
compatibility, but must use the same guard and be narrowed until each UI action
calls a specific domain command.

## 8. Phased execution plan

### Phase 0 -- specification, inventory and baseline

1. Create this single design-and-plan document.
2. Verify the actual mutation inventory against source files and map each to a
   target command.
3. Add a PostgreSQL-backed regression test proving the mapper's existing
   optimistic locking detects a stale second ORM session.
4. Record baseline targeted tests and do not alter production API behavior.

**Done when:** the documented inventory matches the repository, the stale-write
test passes, and the next phase has an approved public API contract.

### Phase 1 -- common API concurrency foundation

1. Add domain errors and a shared lock/version guard.
2. Map `StaleDataError` to sanitized HTTP `409` responses.
3. Add `version` to order-bearing response models.
4. Define shared command payload/response models with expected version and
   idempotency key.
5. Add a frontend `orderCommand` helper that sends version/key and handles 409.

**Done when:** a stale mutation is a predictable 409, never a 500 or silent
overwrite; the UI keeps the user's draft and reloads a safe fresh snapshot.

**Implementation evidence (2026-09-19):** Added shared backend lock/version
guards, structured `ORDER_VERSION_CONFLICT` mapping for explicit and ORM stale
writes, common command payload/result contracts, and version fields in order
list/detail, designer tasks, duplicate board, workload, and finance read data.
Added the frontend order-command helper and structured 409 parsing. The helper
is intentionally not wired into legacy mutation endpoints until Phase 2 converts
those commands. Focused backend tests passed (`54 passed` across the concurrency,
order API, sanitization, Designer Task and duplicate-board suites); focused
frontend tests and production build passed.

### Phase 2 -- highest-risk workflow commands

1. Refactor assignment/reassignment/revocation into one locked command path.
2. Add per-order result objects for bulk assignment; do not roll back valid rows
   because one row is stale.
3. Add expected revision and post-lock ownership validation to Designer Task,
   result submission, Fix approval/rejection and the legacy state endpoint.
4. Dispatch Telegram and Printerval work only after commit.

**Done when:** simultaneous assign/reassign/start/submit attempts cannot give an
order to the wrong person or create invalid result history.

**Implementation evidence (2026-09-19):** Assignment, reassignment and
revocation now lock selected orders in deterministic ID order and validate an
optional expected revision after lock acquisition. Designer Task commands retain
their idempotency ledger and now validate the locked order revision before
start/sub-status/template-missing/result submission. Legacy state and Fix
approval/rejection commands now lock and version-check the order; active
assignments are locked before revalidation. Review synchronization is dispatched
only after the authoritative state transaction commits. Main UI command paths
send revisions, and assignment result submission no longer performs a redundant
second state mutation after it has already entered QC. Focused backend suites
passed in isolated runs (`13 passed` for Designer Task/concurrency and `27
passed` for Orders API); focused frontend suites (`15 passed`) and production
build passed.

### Phase 3 -- metadata, finance, board and external sync

1. Convert notes, deadline, gallery, finance and duplicate-board mutations.
2. Make finance and bulk commands return `succeeded`, `conflicted`, and
   `rejected` item lists.
3. Ensure status sync handles a stale order independently and continues the
   rest of the batch.
4. Route any external-status-driven internal transition through the same domain
   command path with a system actor.

**Done when:** a sync cannot overwrite Tacahu data and one conflicting order
does not fail an entire worker batch.

**Phase 3 implementation evidence (2026-09-19):** Designer note, missing-template
resolution and gallery updates now lock and validate `expected_version` before
writing. Finance mark/unmark and duplicate-domain/check-status bulk commands
lock orders in deterministic ID order and validate the corresponding revision;
duplicate-board drag validates its card revision. The UI sends those revisions
from the current row/card/task. Added regression cases for stale note and
duplicate commands, and for retaining `deadline_tacahu` after a platform sync.
Focused backend tests (`29 passed`), Python syntax compilation, focused frontend
tests (`13 passed`) and production build passed. The temporary duplicate Alembic
revision was corrected by its owning change before the backend suite ran.

### Phase 4 -- conflict UX and observability

1. Add a shared 409 toast/reload flow.
2. Preserve text drafts on conflict and show current server data before retry.
3. Refresh stale rows/boards after conflict; add realtime notification only if
   polling/reload proves insufficient.
4. Add metrics: conflict count by command, stale sync retry, idempotency replay,
   command latency and external reconciliation outcome.

### Phase 5 -- optional processing leases

Only implement after evidence shows repeated simultaneous manual Fix/QC work.
Use TTL, heartbeat, takeover reason and audit. Do not use it for ordinary view,
note, assignment or browser-open actions; it supplements, never replaces,
optimistic versioning.

## 9. Test matrix

- Two independent DB sessions mutate the same order: first commit wins, second
  is stale.
- Two admins assign/reassign one order concurrently.
- Admin revokes while designer starts or submits.
- Two submit requests on one assignment; exactly one result/version sequence is
  accepted unless explicitly modelled as a new submission.
- Fix decision races with Printerval sync.
- Bulk command with stale and valid order rows returns accurate partial results.
- Idempotency replay has no duplicate `WorkflowEvent`, Telegram message or
  external request.
- Conflict response to designer contains no admin-only field.
- PostgreSQL integration tests cover `FOR UPDATE`; SQLite is not accepted as
  evidence for row-lock behavior.

## 10. Rollout and rollback

1. Deploy backend with optional `expected_version` and conflict metrics.
2. Deploy frontend sending version/idempotency keys.
3. Enable enforcement for assignment and Fix commands first.
4. Expand endpoint by endpoint after metrics and regression tests are green.
5. Make expected version mandatory after legacy-client usage reaches zero.

Rollback is a feature-flag change that makes expected-version validation
advisory again. It does not remove the version column, audit events, idempotency
records or transactional locks.

## 11. Phase 0 evidence

- Baseline optimistic-lock regression test: `tests/test_order_concurrency.py`.
- Targeted command/state tests: `tests/test_order_concurrency.py` and
  `tests/test_order_transitions.py`.
- Targeted baseline result: `4 passed` (`ruff check` also passed).
- A full backend regression is a mandatory Phase 1 entry gate and must have its
  final exit status captured before any production API contract changes begin.
