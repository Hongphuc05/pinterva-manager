# Plan — Designer Source Isolation

## Global constraints

1. Preserve all existing designer workflow semantics: task visibility, task start,
   sub-status, missing-template report, result submission, QC feedback, history, and
   finance access.
2. Do not change state-machine rules, idempotency keys, database schema, external
   adapters, workers, or admin API contracts.
3. Do not expose the banned external-system term or its asset domains in a designer
   HTML document, JavaScript/CSS asset, source map, DOM text, URL, API request/response,
   error message, storage value, or direct route.
4. Enforce authorization at the API boundary. Hiding a sidebar item is never
   authorization.
5. Designer data uses a separate response DTO. It is mapped at the API boundary;
   source records remain exact and auditable internally.
6. No automated test may call the live external system. No Docker rebuild, VPS deploy,
   or external write is part of this change.
7. Existing unrelated changes in the main worktree are user-owned. This change stages
   only its own files and hunks.

## Task 1 — Add the delivery boundary

**Files:** `frontend/src/main.tsx`, `frontend/src/App.tsx`, new role-entry modules.

**Consumes:** authenticated `User.role` from `/api/me`.

**Produces:** role-selected, lazy-loaded app tree. The designer chunk has no static
dependency on admin-only modules.

**Steps:**

1. Extract the existing route tree into an admin entry without changing its UI.
2. Add a designer entry with only designer pages and neutral layout components.
3. Use `React.lazy` only after authentication resolves.
4. Add a frontend route guard to redirect direct admin URLs for non-admin accounts.
5. Add tests for designer/admin entry selection and protected-route redirects.

## Task 2 — Build neutral designer read models

**Files:** `app/api/routes/designer_tasks_api.py`, new mapper module and backend tests.

**Consumes:** owned assignment/order records from `list_my_tasks`.

**Produces:** DTO containing only designer-required business fields, safe asset paths,
and neutral field names. It must not contain external-system URLs, field names, or raw
external errors.

**Steps:**

1. Define explicit Pydantic DTOs instead of returning ORM/application dictionaries.
2. Map only local asset paths and omit external order/design-tool links.
3. Sanitize free-text source values before presentation while retaining originals in
   the database.
4. Assert authorization and leakage properties with fixtures containing banned values.

## Task 3 — Isolate designer presentation

**Files:** new designer layout/task components; existing reusable neutral components
only after import-graph audit.

**Consumes:** neutral designer DTO and existing designer-task command endpoints.

**Produces:** the same task list/detail/action behaviour without importing admin
navigation, admin topbar, integration helpers, or external status helpers.

**Steps:**

1. Create a neutral designer shell and navigation.
2. Port task list/detail/action UI with the same commands and idempotency IDs.
3. Replace raw image/link rendering with application-hosted paths.
4. Add component tests for task states and all mutation/error paths.

## Task 4 — Harden admin boundaries

**Files:** `frontend/src/App.tsx`, `app/api/routes/orders_api.py`,
`app/api/routes/platforms_api.py`, authorization tests.

**Consumes:** role guards in `app.api.deps`.

**Produces:** explicit 403 responses for admin source-management endpoints and no
designer route which can load admin source UI.

**Steps:**

1. Audit source-facing routes and attach `require_role("admin")` where missing.
2. Ensure `/platforms/current` has a designer-safe response or replace it in the
designer entry.
3. Test a designer cannot fetch configuration, option lists, sync controls, extension
downloads, or admin-only source routes.

## Task 5 — Add artifact leakage gate

**Files:** frontend test/script and CI-compatible test fixture.

**Consumes:** production build output.

**Produces:** a failing test when designer-delivered static assets or contracts contain
a banned term/domain or source map.

**Steps:**

1. Build the role chunks deterministically.
2. Identify designer assets from Vite manifest/import graph.
3. Scan all designer assets and the bootstrap document case-insensitively.
4. Run the scanner after `npm run build` in local/CI verification.

## Task 6 — Regression, review, and delivery

**Consumes:** all prior changes.

**Produces:** clean, scoped commits with evidence.

**Steps:**

1. Run backend unit/route suites, frontend tests, lint, production build, and leak
scanner.
2. Review diff against `e0d725a` plus working-tree baseline; stage only task files.
3. Commit scoped changes on `main` as explicitly authorized.
4. Push only after all gates pass. Do not rebuild Docker or deploy VPS.
