# Plan — Printerval API-first crawl

1. Add server-only settings and a typed HTTP API client for CSRF form login plus
   `design-job/find` discovery. Classify authentication, rate-limit, network and schema
   failures without logging secrets.
2. Add deterministic mock-transport tests for successful login/discovery, missing team,
   expired session and malformed API responses.
3. Capture the confirmed team scope and API response schema through one read-only manual
   probe, then implement the `PrintervalApiAdapter` discovery mapping.
4. Replace Refresh's discovery path only after API claim/detail/asset contracts are
   independently confirmed. Remove the browser-login UI in the same migration, retaining
   any required write fallback behind an explicit server-side adapter.
