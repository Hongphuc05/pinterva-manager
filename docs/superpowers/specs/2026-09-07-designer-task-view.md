# C4 — Designer task view

## Scope and rulings

Designer works only with an assignment that is still `approved` and belongs to their own
account. A cancelled, draft, or another designer's assignment is invisible and every
write returns the same not-found response, preventing order probing.

**Ruling: Drive verification is mandatory before submit.** The existing `DriveAdapter`
is called inside the idempotent submit operation. A malformed, missing, inaccessible, or
temporarily unverifiable file creates no `ResultVersion` and changes no order state. This
follows `claude.md` §9; format-only validation would create a QC queue containing files
the company cannot open.

**Ruling: starting work is an explicit action.** `sub_status` remains a display field;
the separate Start action is the only designer action that transitions `ASSIGNED` or
`REVISION_REQUESTED` to `IN_PROGRESS`. Changing sub-status alone never changes an order
state.

## API

- `GET /api/my-tasks` returns only the caller's approved assignments whose order is
  `ASSIGNED`, `IN_PROGRESS`, or `REVISION_REQUESTED`, with compact order context, result
  history, and QC comments tied to those result versions.
- `POST /api/assignments/{assignment_id}/start` accepts a bounded client `request_id`.
  It moves an owned task from `ASSIGNED` to `IN_PROGRESS` (`doing`) or from
  `REVISION_REQUESTED` to `IN_PROGRESS` (`fixing`).
- `PATCH /api/assignments/{assignment_id}/sub-status` accepts only `doing`, `fixing`, or
  `done`; it writes no `OrderState`.
- `POST /api/assignments/{assignment_id}/results` accepts a Drive URL and bounded client
  `request_id`. After verification it creates a sequential `ResultVersion`, creates a
  pending `ApprovalRequest(kind="qc", target_id=order.id, target_version_id=result.id)`,
  transitions `IN_PROGRESS → RESULT_SUBMITTED → QC_PENDING`, and sets sub-status `done`.

All state-changing writes use `run_idempotent`; their request fingerprints include the
assignment and payload. Assignment and order rows are locked for the command so two
different request IDs cannot create competing versions.

## UI

`/my-tasks` is designer-only and shows each current task with thumbnail, product context,
deadline, state, sub-status controls, Start button where applicable, previous versions
and QC feedback, plus a Drive submission form only while in progress. It never calls
Printerval or any write adapter.
