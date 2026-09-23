# Printerval support duplicate-image backfill — design

Status: approved for implementation after the operator clarification on
2026-09-23.

## 1. Goal and boundary

This is a **one-time historical backfill**. It reads Printerval design-job rows in
`done`, `confirm`, `review`, and `fix`, stores the order identity/product/preview
metadata in the existing Tacahu PostgreSQL database, and stops. It is not a
recurring crawler.

After the baseline is embedded, future orders follow the existing production
Waiting flow: the production crawl discovers them, the duplicate model compares
them with the historical baseline, and the new row is then appended to the same
support-comparison tables. That future integration is separate from this one-time
backfill command.

The previous live snapshot was approximately 89,403 API records, but the command
must discover and report the current count rather than hard-code that number.

## 2. Explicit decisions

- The data lives in the existing production PostgreSQL database.
- All new objects are isolated in the `support_compare_image` PostgreSQL schema.
- The source code lives under the repository folder `support_compare_image/` and is
  runnable as a small standalone package on another machine.
- Authentication uses the same Printerval account/team as the Tacahu production
  platform, supplied through a secret environment file. The crawler does not read
  or copy secrets from Git.
- The crawl calls only the read-only `/outsource/pod/design-job/find` endpoint.
- The target statuses are exactly `done`, `confirm`, `review`, and `fix`.
- A target-status row is imported without checking `note_outsource` for a result
  link. `note_outsource` is optional metadata only.
- The preview image is extracted with the same priority and recursive behavior as
  the current Waiting/admin crawl helper (`extract_image_url_from_dict_or_html`).
- Missing preview image does not remove the job from the historical snapshot. The
  job is stored with a `preview_missing` quality flag so the final count remains
  reconcilable; the embedding worker can skip it later.
- The backfill stores image URLs and metadata only. It does not download image
  bytes.
- Embedding schema/index creation is deferred until the existing model's dimension,
  metric, and version contract are supplied. This avoids an incorrect vector type
  in the production database.

## 3. Source API and pagination

The crawler mirrors the current production admin crawl's read path:

```text
GET /outsource/pod/design-job/find
  page_size=100
  page_id=0..N
  status=<done|confirm|review|fix>
  time_type=created_at
  job_type=all
  team_outsource=<configured production team>
```

The response envelope and pagination metadata are retained for reconciliation. A
page is considered complete only after its rows and checkpoint are committed to
PostgreSQL. The crawler never calls status, note, assignment, claim, or upload
endpoints.

## 4. Preview extraction

The preview candidate is the same field search used by the current production
Waiting adapter, in this order where present:

```text
thumbnail_url, thumbnail, thumb, product_image, product_thumbnail,
image, image_url, mockup_url, mockup, design_url, artwork_url,
picture, photo, src, ng_src, avatar
```

The extractor recursively checks the same nested containers (`item`, `product`,
`attributes`, `meta_data`, `design`, `mockup`, and `design_job`) and understands
HTML `src`/`ng-src` snippets and relative Printerval asset paths. It records the
field path that produced the URL for quality auditing.

No `source_files`, SKU image, product gallery, or product-page scrape is included
in this backfill. Those are different image roles and could introduce false
duplicates.

## 5. Data model

All tables below are inside `support_compare_image` and do not reuse the
production `orders` or `order_assets` tables.

### `crawl_runs`

One row per invocation. It stores mode, status list, team, page size, counters,
start/finish times, last error, and the operator-visible run ID.

### `crawl_checkpoints`

One row per run/status. It stores the next `page_id`, fetched pages, discovered
rows, stored rows, missing-preview rows, malformed rows, API totals, and completion
state. This makes a network interruption resumable without guessing where to start.

### `crawl_errors`

Append-only error records for malformed rows and page/API failures. It stores the
run/status/page, a classified error code, a safe message, and optional source ID or
payload hash; it never stores the raw customer/API payload.

### `historical_jobs`

One row per Printerval design-job ID. Important fields:

- source system and raw numeric job ID;
- stable `DJ...` external code;
- observed status, team, product name, SKU/category when available;
- preview URL, raw preview URL, and preview extraction path;
- optional `note_outsource` value, never used as an inclusion predicate;
- source payload hash, first/last seen timestamps, and last crawl run;
- `preview_missing` quality flag;
- `ingest_source` (`historical_backfill` initially; future Waiting integration can
  use another value).

The unique key is `(source_system, source_job_id)`. Re-running a page updates the
same row instead of creating a duplicate.

### `image_assets`

One row per normalized preview URL. It stores URL hash, URL, optional content
metadata, and future fetch/embedding state. The initial crawler does not download
the URL.

### `job_images`

Join table between a historical job and its preview asset. The initial role is
`preview`, with position `0` and a primary flag. The table keeps the model handoff
at image level without putting a future vector in the job row.

There is intentionally no vector column in this first migration. Once the model
contract is known, a separate migration can add a pgvector-backed embedding table
with model/version/dimension/metric metadata.

## 6. Run behavior

Supported modes:

- `dry-run`: calls Printerval and reports counts/preview-missing rows without DB
  writes;
- `crawl --limit N`: writes a bounded pilot run;
- `crawl --full-run`: writes all four statuses and requires explicit confirmation;
- `resume --run-id UUID`: continues a failed/interrupted run from checkpoints.

The full run is deliberately not executed during application startup, tests, or
module import. A remote operator must run migration, dry-run, pilot, verification,
then the explicit full command.

## 7. Safety and operations

- The source client is read-only and has no methods for external writes.
- Credentials/session cookies come from an ignored `.env`/secret mount only.
- Logs contain run ID, status, page, and counts; they redact cookies and do not dump
  raw API rows.
- PostgreSQL remains private. For a remote crawler machine, the runbook uses an SSH
  tunnel or private network instead of exposing port 5432 publicly.
- The crawler uses bounded retries, rate limiting, page-level commits, and explicit
  error records.
- The production schema/table count is unchanged except for the controlled
  `support_compare_image` migration.

## 8. Trade-offs

| Decision | Choice | Benefit | Cost |
|---|---|---|---|
| Database placement | Same PostgreSQL, separate schema | No second cluster and easy Support integration | Crawl writes share production DB I/O; rate and batch size must stay conservative |
| Source code | Standalone folder/package | Can be handed to another operator | Duplicates a small read-only API/helper boundary and must be kept aligned |
| Image persistence | URL only | Minimal disk and fast backfill | A later embed run depends on the source URL still being available |
| Missing preview | Store job and flag it | Counts remain auditable; no silent data loss | Embedding worker needs a skip/retry report |
| Page commit | Commit each page with checkpoint | Safe resume and bounded transactions | A partial run is visible until completed |
| Embedding index | Add only after model contract | Prevents wrong dimension/metric in production | Requires a second migration later |

## 9. Acceptance criteria

- Migration creates only the `support_compare_image` schema/tables.
- Dry-run reports totals separately for all four statuses and preview-missing rows.
- A 100-row pilot can stop and resume without duplicate source jobs.
- A repeated page is idempotent.
- Invalid/auth/rate-limit responses are recorded as errors, never as zero rows.
- No Printerval write endpoint is called.
- A remote operator can run the command using only the folder, documented Python
  dependencies, secret env values, and a private/SSH database connection.
