# Plan — C4 Designer task view

1. Add an application service that scopes an owned active assignment, locks assignment
   and order for mutations, and implements start, display-only sub-status, and verified
   result submission with sequential result/QC records and state-machine transitions.
2. Add a JSON task router with role guards, typed request IDs, lazy Drive adapter
   construction, and stable 400/404/503 mappings. Register it with FastAPI.
3. Add backend tests for ownership, state changes, Drive verification failure, new
   version/QC request creation, and idempotent retry.
4. Add the React task page, designer navigation, and route. Test task rendering and a
   successful submission; build and lint the SPA.
