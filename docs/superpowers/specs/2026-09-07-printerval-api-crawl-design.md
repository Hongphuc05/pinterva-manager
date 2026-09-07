# Printerval API-first crawl

## Ruling

Refresh reads only the external `waiting` queue. It never changes a Printerval job back
to Waiting. API credentials live in a gitignored `.env` and are never sent to the SPA.

The API client logs in server-side, keeps its own cookie jar, and calls
`GET /outsource/pod/design-job/find`. `PRINTERVAL_TEAM_OUTSOURCE` is mandatory because
the endpoint rejects an unscoped query; the value must be confirmed from a successful
read-only browser Network request, never guessed from account naming.

API discovery is introduced separately from claim/write operations. The existing
Playwright adapter remains the verified fallback until the API contract for claim,
detail and asset download has been captured and tested. Refresh must not silently mix an
unverified write endpoint into a live crawl.

## Configuration

`PRINTERVAL_API_BASE_URL`, `PRINTERVAL_USERNAME`, `PRINTERVAL_PASSWORD`, and
`PRINTERVAL_TEAM_OUTSOURCE` are server-only settings. Missing settings produce a clear
unavailable result before creating any batch or order state transition.

## First deliverable

An HTTP client supports form-login with CSRF, session reuse, and read-only paginated
Waiting discovery. Tests use `httpx.MockTransport`; no automated test contacts
Printerval. A manual probe records only non-secret request shape and response schema.
