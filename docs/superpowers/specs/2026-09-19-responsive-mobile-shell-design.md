# Responsive and Mobile Shell Design

## Goal

Make Tacahu usable at a half-width desktop viewport, on iPad, and on iPhone without changing the desktop layout at viewport widths of 1280px or more.

## Constraints

- No API, authorization, state-machine, or Print integration behavior changes.
- Desktop (`xl`, 1280px+) keeps the current 256px sidebar, full topbar controls, page spacing, and table layout.
- Tablet (`md` to below `xl`) uses an 80px icon rail that participates in layout; it must never overlap page content.
- Phone (below `md`) uses an off-canvas navigation drawer, a compact topbar, and role-specific bottom navigation.
- Wide data tables remain horizontally scrollable rather than hiding business data.

## Responsive contract

| Range | Navigation | Header and content |
| --- | --- | --- |
| `xl+` | Full 256px sidebar | Current desktop presentation |
| `md`–`xl` | 80px sticky icon rail; labels available through native tooltips | Compact actions and responsive page padding |
| below `md` | Drawer opened by hamburger; role-based bottom navigation | Compact topbar, 16px page padding, safe bottom inset |

## Role navigation

- Admin: Orders, Team progress, Duplicate board, Finance, More.
- Support: Orders, Duplicate board, More.
- Designer: Orders, Finance, More.
- Designer Trello: Duplicate board, Orders, Finance, More.

## Verification

Test 375px and 390px phones, 768px and 820px iPads, 960px split desktop, and 1280px desktop. Verify navigation reachability, no sidebar overlap, preserved routes, and a production frontend build.
