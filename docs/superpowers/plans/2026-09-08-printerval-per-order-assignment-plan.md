# Plan: per-order Printerval designer and status assignment

## Constraints

- Options come from the active platform's Printerval account; never infer them from an
  internal user or another platform.
- Bulk actions validate platform ownership before creating an external request.
- Each external write is per-order, idempotent, independently verified, and auditable.
- A failed/unknown external request must remain visible and must not overwrite a last
  confirmed external Designer/Status observation.

## Tasks

1. Extend the adapter protocol, fake adapter and Playwright adapter with a read-only
   `list_designer_options(order_id)` method. Add offline tests proving that placeholder
   and empty options are excluded and visible labels are preserved exactly.
2. Add an Alembic migration and model for the per-order external assignment request:
   selected designer/status, lifecycle, error/evidence and timestamps. Add an
   application service that validates platform scope and writes one request per order.
3. Add an idempotent Celery worker that loads the platform-specific profile, snapshots
   external order state, sets designer then status, verifies each fresh state, and
   persists the request outcome plus verified observations.
4. Add authenticated APIs for options, single assignment and bulk assignment. The APIs
   enqueue workers only after internal assignment and request rows commit.
5. Update order list/detail responses and React assignment modals: select internal
   designer, external designer and status; show queued/succeeded/failed external sync.
6. Add backend API/service/worker tests and frontend interaction tests; run migration
   graph check, targeted backend suite, lint and frontend build.
