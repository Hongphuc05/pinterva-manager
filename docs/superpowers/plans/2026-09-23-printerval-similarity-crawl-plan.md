# Plan — one-time Printerval support duplicate-image backfill

This plan implements the approved design in
`docs/superpowers/specs/2026-09-23-printerval-similarity-crawl-design.md`.

## Global constraints

- Do not create a second PostgreSQL cluster. Use the existing `DATABASE_URL`, but
  isolate every new object in schema `support_compare_image`.
- Do not modify the existing production `Order`/`OrderAsset` workflow tables.
- The crawler is one-time and read-only against Printerval. Future Waiting orders
  are a separate production integration and are not discovered by this command.
- Import every row returned for the four target statuses; never require a
  `note_outsource` result link.
- Extract only the preview URL using the same behavior as the current Waiting/admin
  crawl. Do not crawl source files, product galleries, or SKU images.
- No image bytes are downloaded in the backfill.
- No vector dimension is guessed before the existing model contract is supplied.
- Keep secrets out of Git, tests, logs, and database payloads.

## Task 1 — Standalone package and operator configuration

### Changes

- Add `support_compare_image/` as a self-contained runnable package.
- Add settings for the production database URL, Printerval base URL, team, and
  username/password or complete session cookie.
- Add `.env.example`, `requirements.txt`, and a redacted operator runbook.

### Verification

- A clean Python environment can import the package after installing only the
  documented dependencies.
- Missing credentials fail with a clear configuration error and never print values.

## Task 2 — Isolated schema and migration

### Changes

- Add a standalone SQLAlchemy base/session and Alembic environment inside the
  folder.
- Use a dedicated Alembic version table inside `support_compare_image` so this
  migration tree does not collide with the application's migration history.
- Create `crawl_runs`, `crawl_checkpoints`, `historical_jobs`, `image_assets`, and
  `job_images`, plus append-only `crawl_errors`.
- Add unique/index constraints for source job identity, URL identity, status, and
  checkpoint resume.

### Verification

- `alembic upgrade head` creates only the new schema/tables.
- Re-running the migration is a no-op.
- The migration does not require or alter the production `orders` tables.

## Task 3 — Read-only Printerval client

### Changes

- Implement the confirmed `/outsource/pod/design-job/find` request contract:
  `page_size=100`, zero-based `page_id`, target `status`, `time_type=created_at`,
  `job_type=all`, and configured `team_outsource`.
- Support either a complete session cookie or server-side form login.
- Preserve API metadata (`total_count`, `page_count`, etc.) for reconciliation.
- Retry only bounded transient/rate-limit failures; do not retry invalid schemas as
  if they were empty pages.
- Expose no write endpoint in the package.

### Verification

- Mock tests cover login/cookie validation, page pagination, reauthentication,
  rate-limit responses, invalid envelopes, and metadata preservation.

## Task 4 — Preview normalizer

### Changes

- Mirror the current production helper's preview-field priority and recursive
  nested search.
- Normalize relative Printerval asset URLs for later download while preserving the
  original raw URL.
- Normalize job identity as raw numeric `source_job_id` plus `DJ...` code.
- Extract product name, status, optional SKU/category, optional outsource note, and
  a hash of the selected fields/raw row for traceability.
- Store target-status rows even when preview is missing; emit a quality flag and
  counter instead of excluding them.

### Verification

- Pure tests cover plain rows, nested product rows, HTML snippets, relative URLs,
  missing preview, invalid IDs, and ignored flag/icon URLs.

## Task 5 — Resumable one-time crawler CLI

### Changes

- Add commands for `dry-run`, bounded `crawl`, explicit `crawl --full-run`, and
  `resume --run-id`.
- Process statuses in a deterministic order: `done`, `confirm`, `review`, `fix`.
- Commit each page's upserts and checkpoint atomically.
- Record malformed rows and page/API errors without turning them into zero rows.
- Add bounded request delay, retry/backoff, and final summary by status and
  preview quality.
- Add `crawl_100k.py`/module entrypoint and avoid running from import/startup.

### Verification

- Mock tests cover idempotent repeated pages, status overlap, page interruption,
  resume, global limit, and no-write-to-Printerval behavior.
- A local pilot writes 100 rows into a test database.

## Task 6 — Handoff documentation

### Changes

- Add `support_compare_image/CRAWL_100K.md` with installation, secret handling,
  SSH tunnel/private DB access, migration, dry-run, pilot, full-run, resume,
  monitoring, backup, and troubleshooting instructions.
- Include an explicit warning that the command writes to production PostgreSQL and
  must be run only after the pilot report is reviewed.

### Verification

- Follow the runbook on a clean machine against a local PostgreSQL test target.
- Confirm no command in the runbook exposes port 5432 publicly or prints secrets.

## Task 7 — Full historical run

This is an operator action after Tasks 1–6 pass. The code and test suite must never
start it automatically. The operator records the final run ID and reconciliation
report as the baseline for the later embedding worker.

## Deferred task — model embedding

After the user supplies model name/version, vector dimension, preprocessing version,
and distance metric, add a second migration and worker contract for embeddings. Do
not add a guessed vector column in this crawl implementation.
