# Designer Source Isolation

## Decision

The browser session of every non-admin operational role (`designer`,
`designer-trello`, and `support`) must receive no literal reference to the external
source system. This is an information-boundary requirement, not an obfuscation
requirement. Internal database columns, adapters, worker names, and the entire admin
UI/API contract remain unchanged. Non-admin users receive a separate frontend entrypoint
and narrow, neutral API contracts.

## Global constraints

1. Preserve all existing non-admin workflow semantics: designer task visibility, task
   start, sub-status, missing-template report, result submission, QC feedback, history,
   finance access, the Trello designer board, and support views.
2. Do not change state-machine rules, idempotency keys, database schema, external
   adapters, workers, or admin API contracts.
3. Do not expose the banned external-system term or its asset domains in a non-admin
   HTML document, JavaScript/CSS asset, source map, DOM text, URL, API request/response,
   error message, storage value, or direct route.
4. Enforce authorization at the API boundary. Hiding a sidebar item is never
   authorization.
5. Non-admin data uses a separate response DTO. It is mapped at the API boundary;
   source records remain exact and auditable internally.
6. No automated test may call the live external system. No Docker rebuild, VPS deploy,
   or external write is part of this change.
7. Existing unrelated changes in the main worktree are user-owned. This change stages
   only its own files and hunks.

## Architecture

The public bootstrap contains authentication and a role switch only. After `/me`, it
lazy-loads either the unchanged admin application or a non-admin application. The
non-admin import graph must never import admin pages, admin layouts,
source-integration modals, source status helpers, or shared components that statically
import them.

The non-admin app uses the existing designer-task command endpoints and new neutral read
models. Its raw external URLs are replaced by application-hosted asset URLs only. Admin
keeps the current integration-facing routes, models, components, and behavior unchanged.

## Authorization

Admin-only frontend routes redirect all non-admin users. Backend endpoints that disclose
source configuration or invoke source synchronization require `admin`. A non-admin user
receives a generic forbidden response, without implementation detail.

## Verification

The production build has an artifact-leak test which scans non-admin-delivered assets
for the banned term and source domains. Backend tests assert the non-admin DTO
contains no banned keys, values, or URLs. Browser-level smoke testing is performed in
staging using an isolated account for each non-admin role before any production deployment.

## Non-goals

- Renaming internal database fields or adapters.
- Changing external-system behaviour.
- Hiding the integration from administrators.
- Deploying or rebuilding runtime infrastructure.
