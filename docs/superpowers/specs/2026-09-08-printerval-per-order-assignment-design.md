# Per-order Printerval designer and status assignment

## Goal

When an admin assigns one or more dashboard orders, they choose both the internal
designer and the exact Designer and Status for each order on that order's active
Printerval platform. The dashboard then shows the independently verified external
Designer and Status.

`DJ3949734` demonstrates the current gap: it is Doing and has a Printerval Designer,
but the dashboard only knows its internal assignment and a status mirror; it does not
hold a verified external-designer observation.

## Scope

- Add an admin-only read endpoint for the current platform's valid Printerval Designer
  options and the six live status labels.
- Add single and bulk dashboard APIs that save the internal assignment and enqueue one
  per-order external assignment request.
- The request records the selected Printerval Designer and desired Printerval Status
  per order. It is not a global default on the internal User record.
- The worker snapshots the current external values, sets Designer, verifies using a
  fresh read, sets Status, and verifies using a fresh read. It records a typed failure
  and evidence without overwriting the confirmed external observation.
- Surface queued/succeeded/failed external synchronization beside the assignment in the
  order list and detail screen.

## External boundary

The dashboard API is the product API. Its external implementation stays behind
`PrintervalAdapter`:

1. `list_designer_options(external_order_id)` reads the actual Designer `<select>` for
   an order under the selected platform account, returning visible labels only.
2. `set_designer` and `set_status` use the site's verified save contracts. The existing
   Playwright adapter is the initial implementation because it already waits for the
   real `/assign-designer` and `/update` responses and independently re-reads state.
3. An HTTP adapter may replace each write only after its request shape and independent
   verification are captured in tests. The dashboard API remains unchanged.

The option list is never guessed from internal users and is never reused across
platforms. It is read from the current platform's authenticated Printerval page. The
admin must select one returned label.

## Data and idempotency

Persist an assignment-level external request containing platform id, selected external
designer label, desired external status, lifecycle (`pending`, `succeeded`, `failed`,
`unknown_outcome`), last error/evidence, and timestamps. This makes the choice auditable
even if an internal user is later renamed or remapped.

For bulk assignment, validate every order belongs to the active platform before writing
anything. Create a separate idempotency key per order based on assignment id, selected
external Designer, and status; one failed order cannot block the rest.

## UI

The single-assignment modal first loads the current platform's Printerval options for
that order. It contains:

- Internal designer select.
- Printerval Designer select, required and populated only from the external list.
- Printerval Status select: Waiting, Doing, Review, Fix, Confirm, Done; default Doing.

Bulk assignment uses the same two external selects and applies them to every selected
order. If an option is unavailable for any selected order, that order is excluded with
a visible reason; no fallback or guessed label is used.

## Non-goals

- Do not derive or overwrite a User's global `printerval_designer_option`.
- Do not silently change an order on a different platform.
- Do not mark an external update successful from a browser DOM immediately after a
  click; success requires a fresh-state read.
- Do not change the internal workflow state machine based only on a failed or unknown
  external result.
