# Allocation Board (C2+C3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement C2 (designer offer + admin manual assignment, FIFO contiguous-block
reference algorithm) and C3 (admin approve/cancel assignment drafts, with auto-replacement
on cancel), plus a drag-and-drop Allocation Board UI in React.

**Architecture:** New `AllocationTool` interface + reference impl → new
`app/application/allocation.py` (pure, testable, no FastAPI/React) → new JSON API
(`allocation_api.py`) → new React page using `@dnd-kit`. No new migration — Phase 1's
schema already has every column needed.

**Tech Stack:** Python (existing app/ layers), `@dnd-kit/core` + `@dnd-kit/sortable`
(new frontend dependency).

**Spec:** `docs/superpowers/specs/2026-09-07-allocation-board-design.md`

## Global Constraints

- No new migration — `batches`, `assignments`, `approval_requests`,
  `approval_decisions`, `users.capacity` already have every column needed (spec §1).
- FIFO contiguous-block algorithm lives behind `AllocationTool` — only a reference
  implementation for V1, never the production tool (spec §2.1, claude.md §3 C2).
- 1 `ApprovalRequest` per order (never one per whole block) — Cancel must release
  exactly one order without touching its siblings (spec §2.3).
- Multi-admin "first valid decision wins": achieved via `run_idempotent`'s own
  idempotency-key cache, keyed by `approval_id` alone (not actor/decision) — do not add
  a separate "already decided" exception path (spec §2.2 decide_assignment).
- Role enforcement stays server-side (`require_role`) — React only hides/shows UI.
- `domain/` stays free of FastAPI/React/Playwright imports.

---

### Task 1: Allocation tool interface + reference implementation + exception

**Files:**
- Create: `app/adapters/allocation/__init__.py` (empty)
- Create: `app/adapters/allocation/interface.py`
- Create: `app/adapters/allocation/reference.py`
- Modify: `app/domain/exceptions.py`
- Test: `tests/test_allocation_reference.py`

**Interfaces:**
- Produces: `AllocationTool` Protocol (`select_block(remaining_order_ids: list[str],
  quantity: int) -> list[str]`), `ReferenceAllocationTool` (its only V1
  implementation), `CapacityExceededError` — all consumed by Task 2/3.

- [ ] **Step 1: Write the interface**

Create `app/adapters/allocation/interface.py`:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AllocationTool(Protocol):
    def select_block(self, remaining_order_ids: list[str], quantity: int) -> list[str]:
        """Return which of remaining_order_ids to grant, at most `quantity` of them.

        V1's contract (claude.md §3 C2, chốt không đổi): FIFO, contiguous block —
        the first `quantity` entries of `remaining_order_ids` in the order given, or
        fewer if remaining_order_ids has fewer than `quantity` entries. Never
        round-robin, never re-pick from an already-granted order. The real
        production allocation tool (chạy nơi khác, không phải repo này) plugs in
        here later without any caller needing to change.
        """
        ...
```

- [ ] **Step 2: Write the reference implementation**

Create `app/adapters/allocation/reference.py`:

```python
from __future__ import annotations


class ReferenceAllocationTool:
    """V1's only AllocationTool — the exact FIFO/contiguous-block algorithm from
    claude.md §3 C2, written for test/demo purposes. NOT the production tool (a
    different one already runs elsewhere) — this exists so the domain layer has a
    correct interface to depend on before that integration happens.
    """

    def select_block(self, remaining_order_ids: list[str], quantity: int) -> list[str]:
        return remaining_order_ids[:quantity]
```

- [ ] **Step 3: Add `CapacityExceededError`**

Edit `app/domain/exceptions.py`, append:

```python
import uuid


class CapacityExceededError(Exception):
    def __init__(self, designer_id: uuid.UUID, capacity: int, held: int, requested: int):
        self.designer_id = designer_id
        self.capacity = capacity
        self.held = held
        self.requested = requested
        super().__init__(
            f"Designer {designer_id} capacity {capacity}, already holding {held}, "
            f"cannot take {requested} more"
        )
```

(`import uuid` goes at the top of the file, above the existing `from app.domain.models
import OrderState` line — merge with any existing imports, don't duplicate.)

- [ ] **Step 4: Write the failing test, then verify it passes**

Create `tests/test_allocation_reference.py`:

```python
from app.adapters.allocation.reference import ReferenceAllocationTool


def test_select_block_takes_first_n_in_order():
    tool = ReferenceAllocationTool()
    assert tool.select_block(["DJ1", "DJ2", "DJ3"], 2) == ["DJ1", "DJ2"]


def test_select_block_returns_fewer_when_not_enough_remain():
    tool = ReferenceAllocationTool()
    assert tool.select_block(["DJ1"], 5) == ["DJ1"]


def test_select_block_empty_when_nothing_remains():
    tool = ReferenceAllocationTool()
    assert tool.select_block([], 5) == []
```

Run: `.venv/bin/pytest tests/test_allocation_reference.py -v` — 3 pass.

- [ ] **Step 5: Lint, commit**

```bash
.venv/bin/ruff check app tests
git add app/adapters/allocation app/domain/exceptions.py tests/test_allocation_reference.py
git commit -m "feat(allocation): AllocationTool interface + FIFO reference implementation"
```

---

### Task 2: `open_allocation`, `request_quantity`, `create_assignment_draft`

**Files:**
- Create: `app/application/allocation.py`
- Test: `tests/test_allocation.py`

**Interfaces:**
- Consumes: `ReferenceAllocationTool`, `CapacityExceededError` (Task 1);
  `apply_transition` (`app/application/order_transitions.py`); `run_idempotent`
  (`app/application/operations.py`); `Order`, `Batch`, `User`, `Assignment`,
  `ApprovalRequest` (`app/adapters/db/models.py`); `OrderState`
  (`app/domain/models.py`).
- Produces: `open_allocation`, `request_quantity`, `create_assignment_draft`,
  `_remaining_order_ids`, `_held_count`, `_grant_orders` (the last 3 are internal,
  Task 3 imports `_remaining_order_ids` and `_grant_orders` too — keep them
  module-level, not prefixed further, so Task 3 can `from app.application.allocation
  import _grant_orders, _remaining_order_ids`).

- [ ] **Step 1: Write `app/application/allocation.py`**

```python
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.adapters.db.models import ApprovalRequest, Assignment, Batch, Order, User
from app.application.operations import run_idempotent
from app.application.order_transitions import apply_transition
from app.domain.exceptions import CapacityExceededError
from app.domain.models import OrderState


def _remaining_order_ids(session: Session, batch_id: uuid.UUID) -> list[Order]:
    """Orders of this batch still open for allocation with no Assignment row yet,
    in a stable order (external_order_id) — locked FOR UPDATE so two concurrent
    callers serialize on this batch instead of double-granting an order. Returns
    Order objects (not just ids) since callers need more than the id."""
    assigned_order_ids = session.query(Assignment.order_id).subquery()
    return (
        session.query(Order)
        .filter(
            Order.batch_id == batch_id,
            Order.state == OrderState.OPEN_FOR_ALLOCATION.value,
            ~Order.id.in_(session.query(assigned_order_ids.c.order_id)),
        )
        .order_by(Order.external_order_id)
        .with_for_update()
        .all()
    )


def _held_count(session: Session, designer_id: uuid.UUID) -> int:
    return (
        session.query(Assignment)
        .filter(Assignment.designer_id == designer_id, Assignment.status.in_(["draft", "approved"]))
        .count()
    )


def _grant_orders(
    session: Session,
    orders: list[Order],
    designer_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    replacement_of_id: uuid.UUID | None = None,
) -> list[Assignment]:
    """Create one Assignment (draft) + one ApprovalRequest per order, transitioning
    each order to ASSIGNMENT_PENDING_APPROVAL. One ApprovalRequest per order (spec
    §2.3) — never one for the whole block — so Cancel can release a single order
    without touching its siblings."""
    assignments: list[Assignment] = []
    for order in orders:
        assignment = Assignment(
            order_id=order.id,
            designer_id=designer_id,
            status="draft",
            replacement_of_id=replacement_of_id,
        )
        session.add(assignment)
        session.flush()
        apply_transition(
            session,
            order,
            OrderState.ASSIGNMENT_PENDING_APPROVAL,
            actor_id=actor_id,
            evidence={"source": "allocation"},
        )
        session.add(ApprovalRequest(kind="assignment", target_id=assignment.id))
        assignments.append(assignment)
    return assignments


def _check_capacity(session: Session, designer_id: uuid.UUID, quantity: int) -> None:
    designer = session.get(User, designer_id)
    if designer is None:
        raise ValueError(f"designer {designer_id} not found")
    if designer.capacity is None:
        return
    held = _held_count(session, designer_id)
    if quantity > designer.capacity - held:
        raise CapacityExceededError(designer_id, designer.capacity, held, quantity)


def open_allocation(session: Session, batch_id: uuid.UUID, idempotency_key: str) -> dict:
    def _do() -> dict:
        batch = session.get(Batch, batch_id)
        if batch is None:
            raise ValueError(f"batch {batch_id} not found")
        orders = (
            session.query(Order)
            .filter_by(batch_id=batch.id, state=OrderState.CLAIMED_IMPORTED.value)
            .all()
        )
        order_ids = []
        for order in orders:
            apply_transition(
                session,
                order,
                OrderState.OPEN_FOR_ALLOCATION,
                actor_id=None,
                evidence={"source": "open_allocation"},
            )
            order_ids.append(order.external_order_id)
        batch.lifecycle_state = "allocating"
        session.add(batch)
        return {"order_ids": order_ids}

    return run_idempotent(session, idempotency_key, "open_allocation", _do)


def request_quantity(
    session: Session,
    allocation_tool,
    designer_id: uuid.UUID,
    batch_id: uuid.UUID,
    quantity: int,
    idempotency_key: str,
) -> dict:
    def _do() -> dict:
        _check_capacity(session, designer_id, quantity)
        remaining = _remaining_order_ids(session, batch_id)
        by_ext_id = {o.external_order_id: o for o in remaining}
        granted_ids = allocation_tool.select_block(list(by_ext_id.keys()), quantity)
        ordered_objs = [by_ext_id[oid] for oid in granted_ids]
        assignments = _grant_orders(session, ordered_objs, designer_id, actor_id=designer_id)
        return {
            "granted_order_ids": [o.external_order_id for o in ordered_objs],
            "assignment_ids": [str(a.id) for a in assignments],
        }

    return run_idempotent(session, idempotency_key, "request_quantity", _do)


def create_assignment_draft(
    session: Session,
    order_id: str,
    designer_id: uuid.UUID,
    actor_id: uuid.UUID,
    idempotency_key: str,
) -> dict:
    def _do() -> dict:
        order = session.query(Order).filter_by(external_order_id=order_id).one_or_none()
        if order is None or order.state != OrderState.OPEN_FOR_ALLOCATION.value:
            raise ValueError(f"order {order_id} is not open for allocation")
        _check_capacity(session, designer_id, 1)
        assignments = _grant_orders(session, [order], designer_id, actor_id=actor_id)
        return {"assignment_id": str(assignments[0].id)}

    return run_idempotent(session, idempotency_key, "create_assignment_draft", _do)
```

- [ ] **Step 2: Write the failing tests, then verify they pass**

Create `tests/test_allocation.py`:

```python
import uuid

from app.adapters.allocation.reference import ReferenceAllocationTool
from app.adapters.db.models import Assignment, Batch, Order, User
from app.application.allocation import (
    create_assignment_draft,
    open_allocation,
    request_quantity,
)
from app.application.auth import hash_password
from app.domain.exceptions import CapacityExceededError
from app.domain.models import OrderState


def _seed_batch_with_orders(db_session, n=3):
    batch = Batch(source="printerval_crawl", owner="ntth", count=n)
    db_session.add(batch)
    db_session.flush()
    orders = []
    for i in range(n):
        order = Order(
            external_order_id=f"DJ{i:07d}", batch_id=batch.id, state=OrderState.CLAIMED_IMPORTED.value
        )
        db_session.add(order)
        orders.append(order)
    db_session.commit()
    return batch, orders


def _seed_designer(db_session, capacity=None, username="designer1"):
    user = User(
        username=username, full_name=username, role="designer",
        password_hash=hash_password("s3cret!"), capacity=capacity,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_open_allocation_transitions_all_claimed_orders(db_session):
    batch, orders = _seed_batch_with_orders(db_session)

    result = open_allocation(db_session, batch.id, "open:1")

    assert set(result["order_ids"]) == {o.external_order_id for o in orders}
    for order in orders:
        db_session.refresh(order)
        assert order.state == OrderState.OPEN_FOR_ALLOCATION.value


def test_request_quantity_grants_contiguous_block_in_order(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=5)
    open_allocation(db_session, batch.id, "open:2")
    designer = _seed_designer(db_session)
    tool = ReferenceAllocationTool()

    result = request_quantity(db_session, tool, designer.id, batch.id, 2, "req:1")

    assert result["granted_order_ids"] == ["DJ0000000", "DJ0000001"]
    assignments = db_session.query(Assignment).filter_by(designer_id=designer.id).all()
    assert len(assignments) == 2
    assert all(a.status == "draft" for a in assignments)


def test_request_quantity_second_caller_gets_the_remaining_block(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=3)
    open_allocation(db_session, batch.id, "open:3")
    d1 = _seed_designer(db_session, username="d1")
    d2 = _seed_designer(db_session, username="d2")
    tool = ReferenceAllocationTool()

    r1 = request_quantity(db_session, tool, d1.id, batch.id, 2, "req:a")
    r2 = request_quantity(db_session, tool, d2.id, batch.id, 2, "req:b")

    assert r1["granted_order_ids"] == ["DJ0000000", "DJ0000001"]
    assert r2["granted_order_ids"] == ["DJ0000002"]  # only 1 left, not an error


def test_request_quantity_rejects_over_capacity(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=5)
    open_allocation(db_session, batch.id, "open:4")
    designer = _seed_designer(db_session, capacity=1)
    tool = ReferenceAllocationTool()

    try:
        request_quantity(db_session, tool, designer.id, batch.id, 2, "req:c")
        assert False, "expected CapacityExceededError"
    except CapacityExceededError:
        pass

    assert db_session.query(Assignment).count() == 0


def test_create_assignment_draft_grants_a_single_named_order(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=2)
    open_allocation(db_session, batch.id, "open:5")
    designer = _seed_designer(db_session)
    admin = User(
        username="admin1", full_name="Admin", role="admin", password_hash=hash_password("s3cret!")
    )
    db_session.add(admin)
    db_session.commit()

    result = create_assignment_draft(
        db_session, orders[1].external_order_id, designer.id, admin.id, "draft:1"
    )

    assignment = db_session.get(Assignment, uuid.UUID(result["assignment_id"]))
    assert assignment.order_id == orders[1].id
    db_session.refresh(orders[1])
    assert orders[1].state == OrderState.ASSIGNMENT_PENDING_APPROVAL.value
```

Run: `.venv/bin/pytest tests/test_allocation.py -v` — all pass.

- [ ] **Step 3: Lint, commit**

```bash
.venv/bin/ruff check app tests
git add app/application/allocation.py tests/test_allocation.py
git commit -m "feat(allocation): open_allocation, request_quantity, create_assignment_draft (C2)"
```

---

### Task 3: `decide_assignment` (C3 — approve/cancel, auto-replacement, multi-admin race)

**Files:**
- Modify: `app/application/allocation.py`
- Test: `tests/test_allocation.py`

**Interfaces:**
- Consumes: `_remaining_order_ids`, `_grant_orders` (Task 2, same module — no new
  import needed, already module-level).
- Produces: `decide_assignment(session, allocation_tool, approval_id, decision,
  actor_id, idempotency_key, reason=None) -> dict` — result always includes
  `actor_id`/`decided_at` so the API layer (Task 4) can tell a genuinely-new decision
  from a cache-hit on an already-decided approval.

- [ ] **Step 1: Add `decide_assignment` to `app/application/allocation.py`**

Add `from datetime import UTC, datetime` and `from app.adapters.db.models import
ApprovalDecision` to the existing imports at the top (merge into the existing
`from app.adapters.db.models import ...` line). Append:

```python
def decide_assignment(
    session: Session,
    allocation_tool,
    approval_id: uuid.UUID,
    decision: str,
    actor_id: uuid.UUID,
    idempotency_key: str,
    reason: str | None = None,
) -> dict:
    """decision is "approve" or "cancel". Multi-admin race (claude.md §10): keyed
    only by approval_id (not actor/decision) so run_idempotent's own cache makes
    the FIRST successful call the only one that ever runs _do() — every later call
    on the same approval_id, from any actor, gets that first call's cached result
    back unchanged. The API layer compares result["actor_id"] to the caller's own
    id to phrase "you decided" vs "already decided by someone else"."""
    if decision not in ("approve", "cancel"):
        raise ValueError(f"unknown decision {decision!r}")

    def _do() -> dict:
        approval = session.get(ApprovalRequest, approval_id)
        if approval is None or approval.kind != "assignment":
            raise ValueError(f"assignment approval {approval_id} not found")
        assignment = session.get(Assignment, approval.target_id)
        order = session.get(Order, assignment.order_id)

        if decision == "approve":
            apply_transition(
                session, order, OrderState.ASSIGNED, actor_id=actor_id,
                evidence={"source": "decide_assignment"},
            )
            assignment.status = "approved"
            approval.status = "approved"
            session.add(
                ApprovalDecision(approval_request_id=approval.id, actor_id=actor_id, decision="approve")
            )
            result = {"decision": "approve", "order_id": order.external_order_id}
        else:
            if not reason:
                raise ValueError("cancel requires a reason")
            apply_transition(
                session, order, OrderState.OPEN_FOR_ALLOCATION, actor_id=actor_id,
                evidence={"source": "decide_assignment"},
            )
            assignment.status = "cancelled"
            assignment.cancel_reason = reason
            approval.status = "cancelled"
            session.add(
                ApprovalDecision(
                    approval_request_id=approval.id, actor_id=actor_id, decision="cancel", comment=reason
                )
            )
            replacement_ids: list[str] = []
            remaining = _remaining_order_ids(session, order.batch_id)
            if remaining:
                by_ext_id = {o.external_order_id: o for o in remaining}
                granted = allocation_tool.select_block(list(by_ext_id.keys()), 1)
                ordered_objs = [by_ext_id[oid] for oid in granted]
                new_assignments = _grant_orders(
                    session, ordered_objs, assignment.designer_id, actor_id=actor_id,
                    replacement_of_id=assignment.id,
                )
                replacement_ids = [str(a.id) for a in new_assignments]
            result = {
                "decision": "cancel",
                "order_id": order.external_order_id,
                "replacement_assignment_ids": replacement_ids,
            }

        result["actor_id"] = str(actor_id)
        result["decided_at"] = datetime.now(UTC).isoformat()
        return result

    return run_idempotent(session, idempotency_key, "decide_assignment", _do)
```

- [ ] **Step 2: Write the failing tests, then verify they pass**

Append to `tests/test_allocation.py`:

```python
from app.adapters.db.models import ApprovalRequest
from app.application.allocation import decide_assignment


def _draft_one_assignment(db_session):
    batch, orders = _seed_batch_with_orders(db_session, n=3)
    open_allocation(db_session, batch.id, f"open:{uuid.uuid4()}")
    designer = _seed_designer(db_session, username=f"d-{uuid.uuid4()}")
    admin = User(
        username=f"admin-{uuid.uuid4()}", full_name="Admin", role="admin",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(admin)
    db_session.commit()
    tool = ReferenceAllocationTool()
    request_quantity(db_session, tool, designer.id, batch.id, 1, f"req:{uuid.uuid4()}")
    order = db_session.query(Order).filter_by(external_order_id="DJ0000000").one()
    assignment = db_session.query(Assignment).filter_by(order_id=order.id).one()
    approval = db_session.query(ApprovalRequest).filter_by(target_id=assignment.id).one()
    return batch, orders, designer, admin, approval, assignment, tool


def test_decide_assignment_approve_moves_order_to_assigned(db_session):
    _, _, _, admin, approval, assignment, tool = _draft_one_assignment(db_session)

    result = decide_assignment(
        db_session, tool, approval.id, "approve", admin.id, f"decide:{uuid.uuid4()}"
    )

    assert result["decision"] == "approve"
    db_session.refresh(assignment)
    assert assignment.status == "approved"
    order = db_session.query(Order).filter_by(id=assignment.order_id).one()
    assert order.state == OrderState.ASSIGNED.value


def test_decide_assignment_cancel_releases_order_and_grants_a_replacement(db_session):
    batch, orders, designer, admin, approval, assignment, tool = _draft_one_assignment(db_session)

    result = decide_assignment(
        db_session, tool, approval.id, "cancel", admin.id, f"decide:{uuid.uuid4()}", reason="đã làm rồi"
    )

    assert result["decision"] == "cancel"
    db_session.refresh(assignment)
    assert assignment.status == "cancelled"
    assert assignment.cancel_reason == "đã làm rồi"
    cancelled_order = db_session.query(Order).filter_by(id=assignment.order_id).one()
    assert cancelled_order.state == OrderState.OPEN_FOR_ALLOCATION.value

    assert len(result["replacement_assignment_ids"]) == 1
    replacement = db_session.get(Assignment, uuid.UUID(result["replacement_assignment_ids"][0]))
    assert replacement.designer_id == designer.id
    assert replacement.replacement_of_id == assignment.id


def test_decide_assignment_cancel_with_no_reason_raises(db_session):
    _, _, _, admin, approval, _, tool = _draft_one_assignment(db_session)

    try:
        decide_assignment(db_session, tool, approval.id, "cancel", admin.id, f"decide:{uuid.uuid4()}")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_decide_assignment_second_call_on_same_approval_returns_first_result_unchanged(db_session):
    """Multi-admin race, claude.md §10: the second admin's attempt must not
    re-execute the decision — it gets the first admin's result back, letting the
    API tell them it was already handled."""
    _, _, _, admin, approval, assignment, tool = _draft_one_assignment(db_session)
    other_admin = User(
        username=f"admin2-{uuid.uuid4()}", full_name="Other Admin", role="admin",
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(other_admin)
    db_session.commit()

    key = f"decide:{approval.id}"  # same key both times, keyed by approval only
    first = decide_assignment(db_session, tool, approval.id, "approve", admin.id, key)
    second = decide_assignment(db_session, tool, approval.id, "cancel", other_admin.id, key, reason="x")

    assert second == first
    assert second["actor_id"] == str(admin.id)  # the FIRST actor, not other_admin
    db_session.refresh(assignment)
    assert assignment.status == "approved"  # cancel from the second call never ran
```

Run: `.venv/bin/pytest tests/test_allocation.py -v` — all pass (7 tests total in the
file after Task 2+3).

- [ ] **Step 3: Lint, commit**

```bash
.venv/bin/ruff check app tests
git add app/application/allocation.py tests/test_allocation.py
git commit -m "feat(allocation): decide_assignment (C3 approve/cancel, auto-replacement, multi-admin race)"
```

---

### Task 4: JSON API (`allocation_api.py`)

**Files:**
- Create: `app/api/routes/allocation_api.py`
- Modify: `app/api/main.py`
- Test: `tests/test_allocation_api.py`

**Interfaces:**
- Consumes: `open_allocation`, `request_quantity`, `create_assignment_draft`,
  `decide_assignment` (Task 2/3); `ReferenceAllocationTool` (Task 1);
  `require_role`/`get_current_user`/`get_db` (`app/api/deps.py`, unchanged).
- Produces: the 5 endpoints in spec §3, consumed by Task 5/6's React pages.

- [ ] **Step 1: Write `app/api/routes/allocation_api.py`**

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.allocation.reference import ReferenceAllocationTool
from app.adapters.db.models import ApprovalRequest, Assignment, Order, User
from app.api.deps import get_current_user, get_db, require_role
from app.application.allocation import (
    _remaining_order_ids,
    create_assignment_draft,
    decide_assignment,
    open_allocation,
    request_quantity,
)
from app.domain.exceptions import CapacityExceededError

router = APIRouter()
_allocation_tool = ReferenceAllocationTool()


class OpenAllocationResponse(BaseModel):
    order_ids: list[str]


@router.post("/batches/{batch_id}/open-allocation", response_model=OpenAllocationResponse)
def api_open_allocation(
    batch_id: str, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)
):
    try:
        result = open_allocation(db, uuid.UUID(batch_id), f"open_allocation:{batch_id}")
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return OpenAllocationResponse(order_ids=result["order_ids"])


class OfferRequest(BaseModel):
    batch_id: str
    quantity: int


class GrantResponse(BaseModel):
    granted_order_ids: list[str]
    assignment_ids: list[str]


@router.post("/allocation/offer", response_model=GrantResponse)
def api_allocation_offer(
    payload: OfferRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    if user.role != "designer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Chỉ designer mới tự offer được")
    try:
        result = request_quantity(
            db, _allocation_tool, user.id, uuid.UUID(payload.batch_id), payload.quantity,
            f"offer:{payload.batch_id}:{user.id}:{uuid.uuid4()}",
        )
    except CapacityExceededError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return GrantResponse(**result)


class AssignRequest(BaseModel):
    order_id: str
    designer_id: str


class AssignResponse(BaseModel):
    assignment_id: str


@router.post("/allocation/assign", response_model=AssignResponse)
def api_allocation_assign(
    payload: AssignRequest, user: User = Depends(require_role("admin")), db: Session = Depends(get_db)
):
    try:
        result = create_assignment_draft(
            db, payload.order_id, uuid.UUID(payload.designer_id), user.id,
            f"assign:{payload.order_id}:{uuid.uuid4()}",
        )
    except (ValueError, CapacityExceededError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return AssignResponse(**result)


class BoardOrderOut(BaseModel):
    id: uuid.UUID
    external_order_id: str
    thumbnail_url: str | None
    sku: str | None
    deadline_at_ext: str | None


class PendingApprovalOut(BaseModel):
    approval_id: uuid.UUID
    order: BoardOrderOut


class BoardDesignerOut(BaseModel):
    id: uuid.UUID
    full_name: str
    capacity: int | None
    held: int
    pending_approvals: list[PendingApprovalOut]


class BoardResponse(BaseModel):
    unassigned: list[BoardOrderOut]
    designers: list[BoardDesignerOut]


@router.get("/allocation/board", response_model=BoardResponse)
def api_allocation_board(
    batch_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    unassigned = [
        BoardOrderOut(
            id=o.id, external_order_id=o.external_order_id, thumbnail_url=o.thumbnail_url,
            sku=o.sku, deadline_at_ext=str(o.deadline_at_ext) if o.deadline_at_ext else None,
        )
        for o in _remaining_order_ids(db, uuid.UUID(batch_id))
    ]

    designers_out = []
    for designer in db.query(User).filter_by(role="designer", active=True).all():
        held = (
            db.query(Assignment)
            .filter(Assignment.designer_id == designer.id, Assignment.status.in_(["draft", "approved"]))
            .count()
        )
        pending = []
        if user.role == "admin":
            draft_assignments = (
                db.query(Assignment)
                .filter_by(designer_id=designer.id, status="draft")
                .all()
            )
            for assignment in draft_assignments:
                approval = (
                    db.query(ApprovalRequest)
                    .filter_by(target_id=assignment.id, kind="assignment", status="pending")
                    .one_or_none()
                )
                if approval is None:
                    continue
                order = db.get(Order, assignment.order_id)
                pending.append(
                    PendingApprovalOut(
                        approval_id=approval.id,
                        order=BoardOrderOut(
                            id=order.id, external_order_id=order.external_order_id,
                            thumbnail_url=order.thumbnail_url, sku=order.sku,
                            deadline_at_ext=str(order.deadline_at_ext) if order.deadline_at_ext else None,
                        ),
                    )
                )
        designers_out.append(
            BoardDesignerOut(
                id=designer.id, full_name=designer.full_name, capacity=designer.capacity,
                held=held, pending_approvals=pending,
            )
        )

    return BoardResponse(unassigned=unassigned, designers=designers_out)


class DecideRequest(BaseModel):
    decision: str
    reason: str | None = None


class DecideResponse(BaseModel):
    decision: str
    order_id: str
    actor_id: str
    decided_by_me: bool
    replacement_assignment_ids: list[str] = []


@router.post("/approvals/{approval_id}/decide", response_model=DecideResponse)
def api_decide_assignment(
    approval_id: str, payload: DecideRequest, user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    try:
        result = decide_assignment(
            db, _allocation_tool, uuid.UUID(approval_id), payload.decision, user.id,
            f"decide_assignment:{approval_id}", reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return DecideResponse(
        decision=result["decision"],
        order_id=result["order_id"],
        actor_id=result["actor_id"],
        decided_by_me=result["actor_id"] == str(user.id),
        replacement_assignment_ids=result.get("replacement_assignment_ids", []),
    )
```

`decided_by_me` is exactly how the frontend (Task 6) tells "your decision went
through" from "someone else already decided this — see spec §2.2's race handling.

- [ ] **Step 2: Register the router**

In `app/api/main.py`, add `from app.api.routes import allocation_api as
allocation_api_routes` and `app.include_router(allocation_api_routes.router,
prefix="/api")` alongside the other `include_router` calls, **before** the
`if FRONTEND_DIST.exists():` block (same placement rule as `orders_api_routes`).

- [ ] **Step 3: Write the tests**

Create `tests/test_allocation_api.py` (follow the exact `client`/`_login` fixture
pattern already used in `tests/test_orders_api.py` — read that file first for the
fixture bodies, do not redefine them differently):

```python
import pytest
from fastapi.testclient import TestClient

from app.adapters.db.models import ApprovalRequest, Assignment, Batch, Order, User
from app.api.deps import get_db
from app.api.main import create_app
from app.application.auth import hash_password
from app.domain.models import OrderState


@pytest.fixture()
def client(db_session):
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, db_session, role, username="user1"):
    user = User(
        username=username, full_name=username, role=role,
        password_hash=hash_password("s3cret!"),
    )
    db_session.add(user)
    db_session.commit()
    client.post("/api/login", json={"username": username, "password": "s3cret!"})
    return user


def _seed_open_batch(db_session, n=3):
    batch = Batch(source="printerval_crawl", owner="ntth", count=n)
    db_session.add(batch)
    db_session.flush()
    for i in range(n):
        db_session.add(
            Order(
                external_order_id=f"DJ{i:07d}", batch_id=batch.id,
                state=OrderState.OPEN_FOR_ALLOCATION.value,
            )
        )
    db_session.commit()
    return batch


def test_offer_requires_designer_role(client, db_session):
    _login(client, db_session, "admin")
    batch = _seed_open_batch(db_session)
    resp = client.post("/api/allocation/offer", json={"batch_id": str(batch.id), "quantity": 1})
    assert resp.status_code == 403


def test_offer_grants_orders_to_a_designer(client, db_session):
    _login(client, db_session, "designer")
    batch = _seed_open_batch(db_session)
    resp = client.post("/api/allocation/offer", json={"batch_id": str(batch.id), "quantity": 2})
    assert resp.status_code == 200
    assert resp.json()["granted_order_ids"] == ["DJ0000000", "DJ0000001"]


def test_assign_requires_admin_role(client, db_session):
    _login(client, db_session, "designer")
    batch = _seed_open_batch(db_session)
    order = db_session.query(Order).filter_by(batch_id=batch.id).first()
    resp = client.post(
        "/api/allocation/assign", json={"order_id": order.external_order_id, "designer_id": str(order.id)}
    )
    assert resp.status_code == 403


def test_board_lists_unassigned_orders_and_designers(client, db_session):
    _login(client, db_session, "admin")
    batch = _seed_open_batch(db_session)

    resp = client.get("/api/allocation/board", params={"batch_id": str(batch.id)})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["unassigned"]) == 3
    assert body["designers"] == []  # no designer users seeded in this test


def test_decide_second_admin_sees_it_was_already_decided(client, db_session):
    _login(client, db_session, "admin", username="admin1")
    batch = _seed_open_batch(db_session)
    designer = User(
        username="d1", full_name="D1", role="designer", password_hash=hash_password("s3cret!")
    )
    db_session.add(designer)
    db_session.commit()

    from app.adapters.allocation.reference import ReferenceAllocationTool
    from app.application.allocation import request_quantity

    request_quantity(db_session, ReferenceAllocationTool(), designer.id, batch.id, 1, "seed-req")
    order = db_session.query(Order).filter_by(external_order_id="DJ0000000").one()
    assignment = db_session.query(Assignment).filter_by(order_id=order.id).one()
    approval = db_session.query(ApprovalRequest).filter_by(target_id=assignment.id).one()

    resp1 = client.post(f"/api/approvals/{approval.id}/decide", json={"decision": "approve"})
    assert resp1.json()["decided_by_me"] is True

    _login(client, db_session, "admin", username="admin2")  # switches `client`'s own session to a 2nd admin
    resp2 = client.post(
        f"/api/approvals/{approval.id}/decide", json={"decision": "cancel", "reason": "x"}
    )
    assert resp2.status_code == 200
    assert resp2.json()["decided_by_me"] is False
    assert resp2.json()["decision"] == "approve"  # admin1's original decision, unchanged
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
.venv/bin/pytest tests/test_allocation_api.py -v
.venv/bin/pytest tests/ -q
.venv/bin/ruff check app tests
git add app/api/routes/allocation_api.py app/api/main.py tests/test_allocation_api.py
git commit -m "feat(api): allocation JSON API (offer, assign, board, decide)"
```

---

### Task 5: React — Allocation Board page (dnd-kit setup, board rendering, drag-to-assign)

**Files:**
- Create: `frontend/src/pages/AllocationBoardPage.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/pages/AllocationBoardPage.test.tsx`

**Interfaces:**
- Consumes: `GET /api/allocation/board?batch_id=`, `POST /api/allocation/assign`
  (Task 4).
- Produces: `/allocation` route, drag-and-drop board — Task 6 adds the offer/approve
  buttons on top of this skeleton.

- [ ] **Step 1: Install dnd-kit**

```bash
cd frontend && npm install @dnd-kit/core
```

- [ ] **Step 2: Write the board page**

Create `frontend/src/pages/AllocationBoardPage.tsx`:

```tsx
import { useState, type ReactNode } from 'react'
import { DndContext, type DragEndEvent, useDraggable, useDroppable } from '@dnd-kit/core'
import { apiFetch } from '../api/client'

type BoardOrder = {
  id: string
  external_order_id: string
  thumbnail_url: string | null
  sku: string | null
  deadline_at_ext: string | null
}

type BoardDesigner = {
  id: string
  full_name: string
  capacity: number | null
  held: number
  pending_approvals: { approval_id: string; order: BoardOrder }[]
}

type BoardData = { unassigned: BoardOrder[]; designers: BoardDesigner[] }

function OrderCard({ order }: { order: BoardOrder }) {
  const { attributes, listeners, setNodeRef, transform } = useDraggable({ id: order.id })
  const style = transform
    ? { transform: `translate(${transform.x}px, ${transform.y}px)` }
    : undefined
  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className="border p-2 mb-2 bg-white cursor-grab"
    >
      {order.thumbnail_url && <img src={order.thumbnail_url} alt="" className="h-10 mb-1" />}
      <div className="text-sm font-mono">{order.external_order_id}</div>
      <div className="text-xs text-gray-500">{order.sku ?? '-'}</div>
    </div>
  )
}

function DesignerColumn({ designer, children }: { designer: BoardDesigner; children: ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: designer.id })
  const full = designer.capacity !== null && designer.held >= designer.capacity
  return (
    <div
      ref={setNodeRef}
      className={`border p-2 w-64 min-h-40 ${isOver ? 'bg-blue-50' : ''}`}
    >
      <h3 className="font-bold mb-2">
        {designer.full_name}: {designer.held}/{designer.capacity ?? '∞'}
        {full && <span className="text-red-600 ml-1">Full</span>}
      </h3>
      {children}
    </div>
  )
}

export function AllocationBoardPage() {
  const [batchId, setBatchId] = useState('')
  const [board, setBoard] = useState<BoardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function loadBoard(id: string) {
    if (!id) return
    try {
      const data = await apiFetch<BoardData>(`/allocation/board?batch_id=${id}`)
      setBoard(data)
      setError(null)
    } catch {
      setError('Không tải được board — kiểm tra batch ID.')
    }
  }

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || !board) return
    const order = board.unassigned.find((o) => o.id === active.id)
    if (!order) return
    try {
      await apiFetch('/allocation/assign', {
        method: 'POST',
        body: JSON.stringify({ order_id: order.external_order_id, designer_id: over.id }),
      })
      await loadBoard(batchId)
    } catch {
      setError('Gán đơn thất bại.')
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">Phân bổ đơn</h1>
      <div className="mb-4">
        <input
          className="border p-1"
          placeholder="Batch ID"
          value={batchId}
          onChange={(e) => setBatchId(e.target.value)}
        />
        <button className="bg-blue-600 text-white px-3 py-1 ml-2" onClick={() => loadBoard(batchId)}>
          Tải
        </button>
      </div>
      {error && <p className="text-red-600 mb-4">{error}</p>}
      {board && (
        <DndContext onDragEnd={handleDragEnd}>
          <div className="flex gap-4">
            <div className="border p-2 w-64 min-h-40">
              <h3 className="font-bold mb-2">Kho đơn chưa gán ({board.unassigned.length})</h3>
              {board.unassigned.map((o) => (
                <OrderCard key={o.id} order={o} />
              ))}
            </div>
            {board.designers.map((d) => (
              <DesignerColumn key={d.id} designer={d}>
                {null}
              </DesignerColumn>
            ))}
          </div>
        </DndContext>
      )}
    </div>
  )
}
```

`ponytail: batch ID is a plain text input for V1 — a follow-up can replace it with a
dropdown fed by GET /api/orders' distinct batch_ids once that's needed; keeping the
board buildable without a batch-picker endpoint no plan task has designed yet.`

- [ ] **Step 3: Wire the route**

In `frontend/src/App.tsx`, add `import { AllocationBoardPage } from
'./pages/AllocationBoardPage'` and a route (inside `<ProtectedRoute>`, same pattern
as the others):

```tsx
<Route
  path="/allocation"
  element={
    <ProtectedRoute>
      <AllocationBoardPage />
    </ProtectedRoute>
  }
/>
```

- [ ] **Step 4: Test**

Create `frontend/src/pages/AllocationBoardPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { AllocationBoardPage } from './AllocationBoardPage'

describe('AllocationBoardPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({ id: '1', role: 'admin', full_name: 'Admin' }),
          })
        }
        if (url.includes('/api/allocation/board')) {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              unassigned: [
                { id: 'o1', external_order_id: 'DJ1', thumbnail_url: null, sku: 'SKU1', deadline_at_ext: null },
              ],
              designers: [{ id: 'd1', full_name: 'Nam', capacity: 5, held: 0, pending_approvals: [] }],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
  })

  it('loads and renders the board after entering a batch id', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <AllocationBoardPage />
        </AuthProvider>
      </BrowserRouter>
    )
    fireEvent.change(screen.getByPlaceholderText('Batch ID'), { target: { value: 'b1' } })
    fireEvent.click(screen.getByText('Tải'))
    await waitFor(() => expect(screen.getByText('DJ1')).toBeInTheDocument())
    expect(screen.getByText(/Nam/)).toBeInTheDocument()
  })
})
```

Run: `cd frontend && npm run test` — passes. Run: `cd frontend && npm run build` —
clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src
git commit -m "feat(frontend): allocation board page (dnd-kit drag-to-assign)"
```

---

### Task 6: React — offer button, approve/cancel actions, nav link

**Files:**
- Modify: `frontend/src/pages/AllocationBoardPage.tsx`
- Modify: `frontend/src/components/AppHeader.tsx` (add nav link, admin-only)
- Test: `frontend/src/pages/AllocationBoardPage.test.tsx`

**Interfaces:**
- Consumes: `POST /api/allocation/offer`, `POST /api/approvals/{id}/decide` (Task 4).

- [ ] **Step 1: Add offer input to each designer column, and pending-approval cards**

Edit `frontend/src/pages/AllocationBoardPage.tsx`. Extend `DesignerColumn` to accept
an `onOffer` callback and render an offer form when the viewer IS that designer
(compare `useAuth().user?.id === designer.id`), plus render `pending_approvals` as
cards with Approve/Cancel buttons calling a new `onDecide` prop:

```tsx
import { useAuth } from '../auth/AuthContext'

// inside DesignerColumn, replace the function signature and body:
function DesignerColumn({
  designer,
  onOffer,
  onDecide,
}: {
  designer: BoardDesigner
  onOffer: (designerId: string, quantity: number) => void
  onDecide: (approvalId: string, decision: 'approve' | 'cancel', reason?: string) => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: designer.id })
  const { user } = useAuth()
  const [quantity, setQuantity] = useState(1)
  const full = designer.capacity !== null && designer.held >= designer.capacity
  const isSelf = user?.id === designer.id

  return (
    <div ref={setNodeRef} className={`border p-2 w-64 min-h-40 ${isOver ? 'bg-blue-50' : ''}`}>
      <h3 className="font-bold mb-2">
        {designer.full_name}: {designer.held}/{designer.capacity ?? '∞'}
        {full && <span className="text-red-600 ml-1">Full</span>}
      </h3>
      {isSelf && (
        <div className="mb-2 flex gap-1">
          <input
            type="number"
            min={1}
            className="border w-16 p-1"
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
          />
          <button
            className="bg-green-600 text-white px-2"
            onClick={() => onOffer(designer.id, quantity)}
          >
            Nhận
          </button>
        </div>
      )}
      {designer.pending_approvals.map((p) => (
        <div key={p.approval_id} className="border p-2 mb-2 bg-yellow-50">
          <div className="text-sm font-mono">{p.order.external_order_id}</div>
          <div className="flex gap-1 mt-1">
            <button
              className="bg-green-600 text-white px-2 text-xs"
              onClick={() => onDecide(p.approval_id, 'approve')}
            >
              Approve
            </button>
            <button
              className="bg-red-600 text-white px-2 text-xs"
              onClick={() => {
                const reason = window.prompt('Lý do huỷ:')
                if (reason) onDecide(p.approval_id, 'cancel', reason)
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
```

Add `import { useState } from 'react'` is already present (top of file); ensure it's
imported — it already is from Task 5's `useEffect, useState` import.

In `AllocationBoardPage`, add the two handlers and pass them to `DesignerColumn`:

```tsx
async function handleOffer(designerId: string, quantity: number) {
  try {
    await apiFetch('/allocation/offer', {
      method: 'POST',
      body: JSON.stringify({ batch_id: batchId, quantity }),
    })
    await loadBoard(batchId)
  } catch {
    setError('Offer thất bại — có thể vượt capacity.')
  }
}

async function handleDecide(approvalId: string, decision: 'approve' | 'cancel', reason?: string) {
  try {
    const result = await apiFetch<{ decided_by_me: boolean }>(`/approvals/${approvalId}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision, reason }),
    })
    if (!result.decided_by_me) {
      setError('Đơn này đã được admin khác xử lý trước đó.')
    }
    await loadBoard(batchId)
  } catch {
    setError('Quyết định thất bại.')
  }
}
```

Update the `.map` call rendering `DesignerColumn` to pass the new props:

```tsx
{board.designers.map((d) => (
  <DesignerColumn key={d.id} designer={d} onOffer={handleOffer} onDecide={handleDecide}>
    {null}
  </DesignerColumn>
))}
```

(`children` prop on `DesignerColumn` becomes unused now that pending approvals render
internally — remove the `children` parameter from its signature and the `{null}`
call-site prop entirely.)

- [ ] **Step 2: Add nav link**

Edit `frontend/src/components/AppHeader.tsx` — add, admin-only, a link to
`/allocation` next to the existing "Pinterval Ops" link:

```tsx
{user.role === 'admin' && (
  <Link to="/allocation" className="underline">
    Phân bổ
  </Link>
)}
```

placed inside the existing header `<div>`/`<header>` structure — read the current
file first and slot it next to the existing links rather than guessing exact JSX
nesting.

- [ ] **Step 3: Extend the test**

Add to `frontend/src/pages/AllocationBoardPage.test.tsx` (extend the existing mock to
also answer `/allocation/offer` and `/approvals/`):

```tsx
it('lets the logged-in designer offer a quantity', async () => {
  ;(fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, init?: RequestInit) => {
    if (url.includes('/api/me')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: async () => ({ id: 'd1', role: 'designer', full_name: 'Nam' }),
      })
    }
    if (url.includes('/api/allocation/offer')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: async () => ({ granted_order_ids: ['DJ1'], assignment_ids: ['a1'] }),
      })
    }
    if (url.includes('/api/allocation/board')) {
      return Promise.resolve({
        ok: true, status: 200,
        json: async () => ({
          unassigned: [],
          designers: [{ id: 'd1', full_name: 'Nam', capacity: 5, held: 0, pending_approvals: [] }],
        }),
      })
    }
    return Promise.reject(new Error(`unexpected fetch: ${url} ${init?.method}`))
  })

  render(
    <BrowserRouter>
      <AuthProvider>
        <AllocationBoardPage />
      </AuthProvider>
    </BrowserRouter>
  )
  fireEvent.change(screen.getByPlaceholderText('Batch ID'), { target: { value: 'b1' } })
  fireEvent.click(screen.getByText('Tải'))
  await waitFor(() => expect(screen.getByText('Nhận')).toBeInTheDocument())
  fireEvent.click(screen.getByText('Nhận'))
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith('/api/allocation/offer', expect.anything())
  )
})
```

Run: `cd frontend && npm run test` — both tests in the file pass. Run:
`cd frontend && npm run build` — clean.

- [ ] **Step 4: Full verification, commit**

```bash
.venv/bin/pytest tests/ -q
.venv/bin/ruff check app tests
cd frontend && npm run build && npm run test
```

```bash
git add frontend/src
git commit -m "feat(frontend): allocation board offer/approve/cancel actions"
```
