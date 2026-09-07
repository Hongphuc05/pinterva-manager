# Plan — Kanban ops board

1. Add an admin-only read model that groups all orders, joins active designers, and
   derives dead-letter/state warning badges without mutating data.
2. Expose and test `GET /api/kanban`, then register the router.
3. Add a responsive, read-only React board and admin navigation link. Test a card and
   its warning display; run the complete verification suite.
