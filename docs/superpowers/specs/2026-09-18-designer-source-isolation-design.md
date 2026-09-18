# Designer Source Isolation

## Decision

The browser session of a designer must receive no literal reference to the external
source system.  This is an information-boundary requirement, not an obfuscation
requirement.  Internal database columns, adapters, worker names, and admin APIs remain
unchanged.  A designer receives a separate frontend entrypoint and a narrow, neutral
API contract.

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
5. Designer data uses a separate response DTO.  It is mapped at the API boundary;
   source records remain exact and auditable internally.
6. No automated test may call the live external system. No Docker rebuild, VPS deploy,
   or external write is part of this change.
7. Existing unrelated changes in the main worktree are user-owned. This change stages
   only its own files and hunks.

## Architecture

The public bootstrap contains authentication and a role switch only. After `/me`, it
lazy-loads either an admin application or a designer application. The designer import
graph must never import admin pages, admin layouts, source-integration modals, source
status helpers, or shared components that statically import them.

The designer app uses the existing designer-task command endpoints and a new neutral
read model.  Its raw external URLs are replaced by application-hosted asset URLs only.
Admin keeps the current integration-facing routes and models.

## Authorization

Admin-only frontend routes redirect non-admin users. Backend endpoints that disclose
source configuration or invoke source synchronization require `admin`.  A designer
receives a generic forbidden response, without implementation detail.

## Verification

The production build has an artifact-leak test which scans the designer-delivered
assets for the banned term and source domains. Backend tests assert the designer DTO
contains no banned keys, values, or URLs. Browser-level smoke testing is performed in
staging using an isolated designer account before any production deployment.

## Non-goals

- Renaming internal database fields or adapters.
- Changing external-system behaviour.
- Hiding the integration from administrators.
- Deploying or rebuilding runtime infrastructure.
