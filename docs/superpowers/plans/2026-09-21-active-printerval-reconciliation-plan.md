# Plan: active Printerval reconciliation

Global constraints: source Printerval is read-only; PostgreSQL owns internal state;
tab sync only affects its snapshot; Designer-to-Admin workflows remain unchanged.

1. Add a summary-only active-feed reconciliation service and focused fake-adapter
   tests for new Waiting, tracked Fix, paid Done -> Fix, and untracked non-Waiting.
   Produces structured counts without per-row detail fetches.
2. Route scheduled/Topbar global jobs through that service while retaining explicit
   order-ID jobs through the existing selected-order service. Preserve platform sync
   state and no-overlap behavior.
3. Verify existing paid-Fix submission tests, add regression coverage for the new
   scheduler path, run backend focused tests, lint, frontend build, and diff check.
