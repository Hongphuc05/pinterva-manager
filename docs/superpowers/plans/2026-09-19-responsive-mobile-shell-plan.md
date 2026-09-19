# Responsive and Mobile Shell Implementation Plan

## Task 1 — Responsive navigation shell

**Consumes:** authenticated user role and route path.

**Produces:** full desktop sidebar at `xl`, in-flow tablet rail at `md`, and mobile drawer plus bottom navigation below `md`.

1. Add drawer state in `DashboardLayout`.
2. Give `Sidebar` compact/tablet and drawer/mobile variants without duplicating menu authority.
3. Add a role-aware mobile bottom navigation.
4. Keep `xl` desktop classes equal to existing values.

## Task 2 — Responsive topbar

**Consumes:** drawer opener, role, current route, existing sync/crawl actions.

**Produces:** mobile hamburger, truncation-safe title, compact controls below desktop widths.

1. Add a hamburger that opens the mobile drawer.
2. Hide text labels before `xl` while retaining title/tooltips and actions.
3. Preserve all existing action handlers and modals.

## Task 3 — Page safety and verification

**Consumes:** existing pages, table wrappers, boards.

**Produces:** mobile-safe spacing and non-overlapping scroll regions.

1. Add bottom inset and responsive padding in the common layout.
2. Retain horizontal scrolling for wide tables and boards.
3. Run targeted frontend tests and production build.
