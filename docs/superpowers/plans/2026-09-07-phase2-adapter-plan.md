# Phase 2 — Adapter tích hợp xác định — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Printerval (Playwright) and Google Sheets/Drive adapters — typed,
independently testable business-tool methods — plus the shared Playwright reliability
package and a supervised smoke-test harness for verifying write operations against the
real Printerval site without leaving it in a modified state.

**Architecture:** Every adapter is a `Protocol` (interface) with two implementations: a
`fake_*` (in-memory, used by all automated `pytest`/CI tests) and a real one (Playwright
for Printerval, `google-api-python-client` for Sheets/Drive). Automated tests never touch
the real Printerval site or real Google APIs (one narrow exception: a Google integration
test that creates and deletes its own throwaway spreadsheet, skipped automatically when
the credential file is absent). Verifying the real Printerval adapter happens through a
reusable snapshot→act→verify→restore→verify-restore harness, exercised both by a
deterministic unit test (against the fake adapter) and by supervised manual runs against
the live site.

**Tech Stack:** Playwright (Python, sync API) for Printerval; `google-api-python-client`
+ `google-auth` for Sheets/Drive; Pydantic v2 for all result models (matches Phase 1).

**Spec:** `docs/superpowers/specs/2026-09-07-phase2-adapter-design.md` (adapter
architecture) and `claude.md` §4, §7, §8, §11, §13, §16, §17 (contracts, error taxonomy,
Playwright rules, confirmed context, open tech debt).

## Global Constraints

- Playwright uses real Chrome (`channel="chrome"`, not headless,
  `--disable-blink-features=AutomationControlled`) — confirmed necessary to bypass
  Printerval's Cloudflare protection (claude.md §16).
- Every write to the real Printerval site — including during implementation, not just in
  a later "testing phase" — must follow: snapshot original state → act → verify → restore
  → verify restore succeeded. On any failure mid-sequence, still attempt restore, and
  raise loudly (never silently leave the site in a modified state). Prefer an order
  already in `Done` status when a specific real order is needed for a write test; not
  mandatory when the method under test requires a different status (e.g. `set_designer`
  only applies to `waiting` orders).
- `pytest` (run automatically in CI on every push) never touches the real Printerval site
  and never touches real Google APIs with one narrow exception: a Google integration test
  that creates and deletes its own throwaway spreadsheet, gated by
  `pytest.mark.skipif` on the credential file's absence (CI has no credential, so it
  auto-skips there).
- Job type filter is hard-coded to `"2D"` for V1 (claude.md §16).
- Error classification is exactly: `VALIDATION | AUTH | RATE_LIMIT | TRANSIENT_NETWORK | EXTERNAL_CHANGED | UNKNOWN_OUTCOME | PERMANENT_EXTERNAL | BUG` (claude.md §11).
- Every adapter method returns a typed (Pydantic) result carrying `success`, `evidence`,
  `error_class`, `retryable` at minimum — never a bare bool/dict, never a raised
  exception for expected business failures (claude.md §8).
- No Playwright/Selenium primitive is ever exposed outside the adapter module — each
  method performs exactly one business action (claude.md §8).
- `credentials/google-service-account.json` already exists locally (gitignored, never
  committed) — service account email
  `pinterval-sheets-adapter@gen-lang-client-0481902654.iam.gserviceaccount.com`.
- Google Sheets is a one-way archive only — the adapter never reads Sheet content back to
  make a decision (claude.md §9).

---

### Task 1: Shared models, error taxonomy, and adapter interfaces

**Files:**
- Create: `app/adapters/errors.py`
- Create: `app/adapters/printerval/__init__.py`
- Create: `app/adapters/printerval/models.py`
- Create: `app/adapters/printerval/interface.py`
- Create: `app/adapters/google/__init__.py`
- Create: `app/adapters/google/models.py`
- Create: `app/adapters/google/sheets_interface.py`
- Create: `app/adapters/google/drive_interface.py`
- Test: `tests/test_printerval_models.py`

**Interfaces:**
- Consumes: nothing (pure Pydantic models + `typing.Protocol`, no I/O).
- Produces: `app.adapters.errors.ErrorClass` (8-member str Enum); Printerval result
  models `DiscoverResult`, `OrderDetailResult`, `WriteResult`, `AssetResult`,
  `OrderSummary`; `app.adapters.printerval.interface.PrintervalAdapter` (a
  `@runtime_checkable Protocol` with 6 methods: `discover_orders`, `get_order_detail`,
  `set_designer`, `set_status`, `attach_result_link`, `download_asset`); Google result
  models `ExportResult`, `DriveVerifyResult`; `SheetsAdapter`/`DriveAdapter` Protocols
  (`export_snapshot`, `verify_url`). Every later task in this plan imports these exact
  names.

- [ ] **Step 1: Create `app/adapters/errors.py`**

```python
from enum import Enum


class ErrorClass(str, Enum):
    VALIDATION = "VALIDATION"
    AUTH = "AUTH"
    RATE_LIMIT = "RATE_LIMIT"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    EXTERNAL_CHANGED = "EXTERNAL_CHANGED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    PERMANENT_EXTERNAL = "PERMANENT_EXTERNAL"
    BUG = "BUG"
```

- [ ] **Step 2: Create `app/adapters/printerval/__init__.py`** (empty)

- [ ] **Step 3: Create `app/adapters/printerval/models.py`**

```python
from __future__ import annotations

from pydantic import BaseModel

from app.adapters.errors import ErrorClass


class AdapterResult(BaseModel):
    success: bool
    evidence: dict = {}
    error_class: ErrorClass | None = None
    retryable: bool = False


class OrderSummary(BaseModel):
    external_order_id: str
    product_name: str
    thumbnail_url: str | None = None
    designer: str | None = None
    status: str


class DiscoverResult(AdapterResult):
    orders: list[OrderSummary] = []
    cursor: str | None = None


class OrderDetailResult(AdapterResult):
    external_order_id: str | None = None
    designer: str | None = None
    status: str | None = None
    note_outsource: str = ""
    order_note: str = ""
    created_at: str | None = None
    order_created_at: str | None = None
    deadline_at: str | None = None
    has_uploaded_design: bool = False


class WriteResult(AdapterResult):
    external_order_id: str
    observed_state: dict = {}


class AssetResult(AdapterResult):
    external_order_id: str
    local_path: str | None = None
    checksum: str | None = None
```

- [ ] **Step 4: Create `app/adapters/printerval/interface.py`**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.adapters.printerval.models import (
    AssetResult,
    DiscoverResult,
    OrderDetailResult,
    WriteResult,
)


@runtime_checkable
class PrintervalAdapter(Protocol):
    def discover_orders(
        self,
        status: str,
        job_type: str = "2D",
        limit: int = 40,
        cursor: str | None = None,
    ) -> DiscoverResult: ...

    def get_order_detail(self, external_order_id: str) -> OrderDetailResult: ...

    def set_designer(self, external_order_id: str, designer_option: str) -> WriteResult: ...

    def set_status(self, external_order_id: str, target_status: str) -> WriteResult: ...

    def attach_result_link(self, external_order_id: str, drive_url: str) -> WriteResult: ...

    def download_asset(self, external_order_id: str) -> AssetResult: ...
```

- [ ] **Step 5: Create `app/adapters/google/__init__.py`** (empty)

- [ ] **Step 6: Create `app/adapters/google/models.py`**

```python
from __future__ import annotations

from pydantic import BaseModel

from app.adapters.errors import ErrorClass


class ExportResult(BaseModel):
    success: bool
    rows_written: int = 0
    error_class: ErrorClass | None = None


class DriveVerifyResult(BaseModel):
    success: bool
    exists: bool = False
    accessible: bool = False
    error_class: ErrorClass | None = None
```

- [ ] **Step 7: Create `app/adapters/google/sheets_interface.py`**

```python
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.adapters.google.models import ExportResult


@runtime_checkable
class SheetsAdapter(Protocol):
    def export_snapshot(
        self, rows: list[dict], sheet_id: str, exported_at: datetime
    ) -> ExportResult: ...
```

- [ ] **Step 8: Create `app/adapters/google/drive_interface.py`**

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.adapters.google.models import DriveVerifyResult


@runtime_checkable
class DriveAdapter(Protocol):
    def verify_url(self, drive_url: str) -> DriveVerifyResult: ...
```

- [ ] **Step 9: Write the failing test — `tests/test_printerval_models.py`**

```python
from app.adapters.errors import ErrorClass
from app.adapters.printerval.models import DiscoverResult, WriteResult


def test_error_class_has_all_eight_values():
    assert {e.value for e in ErrorClass} == {
        "VALIDATION",
        "AUTH",
        "RATE_LIMIT",
        "TRANSIENT_NETWORK",
        "EXTERNAL_CHANGED",
        "UNKNOWN_OUTCOME",
        "PERMANENT_EXTERNAL",
        "BUG",
    }


def test_discover_result_defaults():
    result = DiscoverResult(success=True)
    assert result.orders == []
    assert result.cursor is None
    assert result.error_class is None


def test_write_result_requires_external_order_id():
    result = WriteResult(success=True, external_order_id="DJ0000001")
    assert result.observed_state == {}


def test_write_result_accepts_error_class_from_plain_string():
    result = WriteResult(
        success=False, external_order_id="DJ0000001", error_class="VALIDATION"
    )
    assert result.error_class == ErrorClass.VALIDATION
```

- [ ] **Step 10: Run test to verify it passes**

Run: `pytest tests/test_printerval_models.py -v`
Expected: all 4 tests PASS (pure Pydantic, no new dependency needed — Pydantic already
in `pyproject.toml` from Phase 1)

- [ ] **Step 11: Commit**

```bash
git add app/adapters/errors.py app/adapters/printerval app/adapters/google tests/test_printerval_models.py
git commit -m "feat: adapter result models, error taxonomy, Printerval/Google Protocols"
```

---

### Task 2: Playwright reliability package

**Files:**
- Modify: `pyproject.toml` (add `playwright` dependency)
- Create: `app/adapters/playwright_support.py`
- Test: `tests/test_playwright_support.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `app.adapters.playwright_support.playwright_session(profile_dir: str = "chrome-profile", headless: bool = False)`
  (context manager yielding a Playwright `Page`), `with_retry(fn: Callable[[], T], max_attempts: int = 3, base_delay: float = 0.5) -> T`
  (retries `fn()` while its result has `.retryable is True` and `.success is False`),
  `capture_evidence(page, label: str) -> dict` (screenshot + HTML dump, returns paths).
  Tasks 5 and 6 (real Printerval adapter) use all three.

- [ ] **Step 1: Add `playwright` to `pyproject.toml` dependencies**

In the `dependencies` list (alongside `fastapi`, `sqlalchemy`, etc.), add:

```toml
  "playwright>=1.46",
```

Run: `pip install -e ".[dev]"` to install it into the venv.

- [ ] **Step 2: Write the failing tests — `tests/test_playwright_support.py`**

```python
from pathlib import Path

from app.adapters.playwright_support import capture_evidence, with_retry


class _FakeResult:
    def __init__(self, success, retryable):
        self.success = success
        self.retryable = retryable


def test_with_retry_returns_immediately_on_success():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        return _FakeResult(success=True, retryable=False)

    result = with_retry(fn, max_attempts=3, base_delay=0.01)
    assert result.success is True
    assert calls["count"] == 1


def test_with_retry_returns_immediately_on_non_retryable_failure():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        return _FakeResult(success=False, retryable=False)

    result = with_retry(fn, max_attempts=3, base_delay=0.01)
    assert result.success is False
    assert calls["count"] == 1


def test_with_retry_retries_up_to_max_attempts_on_retryable_failure():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        return _FakeResult(success=False, retryable=True)

    result = with_retry(fn, max_attempts=3, base_delay=0.01)
    assert result.success is False
    assert calls["count"] == 3


def test_with_retry_stops_once_a_later_attempt_succeeds():
    calls = {"count": 0}

    def fn():
        calls["count"] += 1
        if calls["count"] < 2:
            return _FakeResult(success=False, retryable=True)
        return _FakeResult(success=True, retryable=False)

    result = with_retry(fn, max_attempts=3, base_delay=0.01)
    assert result.success is True
    assert calls["count"] == 2


class _FakePage:
    def __init__(self, url="https://example.test/order/1"):
        self.url = url

    def screenshot(self, path):
        Path(path).write_bytes(b"fake-png-bytes")

    def content(self):
        return "<html>fake</html>"


def test_capture_evidence_writes_screenshot_and_html(tmp_path, monkeypatch):
    import app.adapters.playwright_support as ps

    monkeypatch.setattr(ps, "EVIDENCE_DIR", tmp_path / "evidence")

    page = _FakePage()
    evidence = capture_evidence(page, "test_label")

    assert Path(evidence["screenshot_path"]).exists()
    assert Path(evidence["html_path"]).read_text() == "<html>fake</html>"
    assert evidence["url"] == page.url
    assert "captured_at" in evidence
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_playwright_support.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.playwright_support'`

- [ ] **Step 4: Create `app/adapters/playwright_support.py`**

```python
from __future__ import annotations

import random
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

from playwright.sync_api import Page, sync_playwright

EVIDENCE_DIR = Path("playwright-evidence")

T = TypeVar("T")


@contextmanager
def playwright_session(profile_dir: str = "chrome-profile", headless: bool = False):
    """Launch a persistent Chrome profile, yield the Page to use.

    The profile directory must already be logged into Printerval (done once,
    interactively, by a human — Cloudflare + the site's login flow are not
    automated here). Reusing the persistent profile avoids re-login on every
    run, matching how Phase 0's exploration worked.
    """
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile_dir,
            channel="chrome",
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            yield page
        finally:
            context.close()


def with_retry(fn: Callable[[], T], max_attempts: int = 3, base_delay: float = 0.5) -> T:
    """Call fn() up to max_attempts times while its result is retryable.

    fn() must return an object with boolean `.success` and `.retryable`
    attributes (every AdapterResult subclass qualifies). A successful result,
    or a failure with retryable=False, returns immediately on the first
    attempt.
    """
    last_result = None
    for attempt in range(1, max_attempts + 1):
        result = fn()
        if result.success or not result.retryable:
            return result
        last_result = result
        if attempt < max_attempts:
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
            time.sleep(delay)
    return last_result


def capture_evidence(page: Page, label: str) -> dict:
    """Screenshot + HTML dump + timestamp; returns paths for an `evidence` field."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    base = f"{label}_{timestamp}"
    screenshot_path = EVIDENCE_DIR / f"{base}.png"
    html_path = EVIDENCE_DIR / f"{base}.html"
    page.screenshot(path=str(screenshot_path))
    html_path.write_text(page.content())
    return {
        "screenshot_path": str(screenshot_path),
        "html_path": str(html_path),
        "url": page.url,
        "captured_at": timestamp,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_playwright_support.py -v`
Expected: all 5 tests PASS. `playwright_session` itself has no automated test — it
requires a real, already-logged-in Chrome profile, which is exercised only by the manual
smoke test in Tasks 5/6, not by `pytest`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/adapters/playwright_support.py tests/test_playwright_support.py
git commit -m "feat: Playwright reliability package (session, retry+backoff, evidence capture)"
```

---

### Task 3: Fake Printerval adapter

**Files:**
- Create: `app/adapters/printerval/fake_adapter.py`
- Test: `tests/test_printerval_fake_adapter.py`

**Interfaces:**
- Consumes: `app.adapters.printerval.models.*` (Task 1).
- Produces: `app.adapters.printerval.fake_adapter.FakePrintervalAdapter` — an in-memory
  implementation of `PrintervalAdapter`, with `.add_order(**kwargs)` to seed orders. Task
  4 (smoke harness tests) and Task 9 (contract tests) both use this class.

- [ ] **Step 1: Write the failing tests — `tests/test_printerval_fake_adapter.py`**

```python
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter


def _seeded_adapter():
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id="DJ0000001",
        product_name="Mug in cứng",
        designer=None,
        status="Waiting",
    )
    adapter.add_order(
        external_order_id="DJ0000002",
        product_name="Áo thun",
        designer="Nguyễn Thị Thuý Hường - 2D Prin",
        status="Doing",
    )
    return adapter


def test_discover_orders_filters_by_status():
    adapter = _seeded_adapter()
    result = adapter.discover_orders(status="Waiting")
    assert result.success is True
    assert [o.external_order_id for o in result.orders] == ["DJ0000001"]


def test_get_order_detail_returns_full_fields():
    adapter = _seeded_adapter()
    result = adapter.get_order_detail("DJ0000002")
    assert result.success is True
    assert result.designer == "Nguyễn Thị Thuý Hường - 2D Prin"
    assert result.status == "Doing"


def test_get_order_detail_missing_order_is_validation_error():
    adapter = _seeded_adapter()
    result = adapter.get_order_detail("DJ9999999")
    assert result.success is False
    assert result.error_class == "VALIDATION"


def test_set_designer_updates_and_is_observable():
    adapter = _seeded_adapter()
    write_result = adapter.set_designer("DJ0000001", "Nguyễn Thị Thuý Hường - 2D Prin")
    assert write_result.success is True
    detail = adapter.get_order_detail("DJ0000001")
    assert detail.designer == "Nguyễn Thị Thuý Hường - 2D Prin"


def test_set_status_updates_and_is_observable():
    adapter = _seeded_adapter()
    write_result = adapter.set_status("DJ0000001", "Doing")
    assert write_result.success is True
    detail = adapter.get_order_detail("DJ0000001")
    assert detail.status == "Doing"


def test_attach_result_link_updates_observed_state():
    adapter = _seeded_adapter()
    write_result = adapter.attach_result_link(
        "DJ0000002", "https://drive.google.com/file/d/abc123/view"
    )
    assert write_result.success is True
    assert write_result.observed_state["drive_url"].startswith("https://drive.google.com")


def test_download_asset_returns_local_path():
    adapter = _seeded_adapter()
    result = adapter.download_asset("DJ0000001")
    assert result.success is True
    assert result.local_path.endswith("DJ0000001.png")


def test_write_methods_reject_unknown_order():
    adapter = _seeded_adapter()
    result = adapter.set_designer("DJ_NOPE", "x")
    assert result.success is False
    assert result.error_class == "VALIDATION"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_printerval_fake_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.printerval.fake_adapter'`

- [ ] **Step 3: Create `app/adapters/printerval/fake_adapter.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from app.adapters.printerval.models import (
    AssetResult,
    DiscoverResult,
    OrderDetailResult,
    OrderSummary,
    WriteResult,
)


@dataclass
class _FakeOrder:
    external_order_id: str
    product_name: str
    designer: str | None
    status: str
    note_outsource: str = ""
    order_note: str = ""
    created_at: str = "2026-01-01T00:00:00"
    order_created_at: str = "2026-01-01T00:00:00"
    deadline_at: str = "2026-01-10T00:00:00"
    has_uploaded_design: bool = False
    drive_url: str | None = None


class FakePrintervalAdapter:
    """In-memory adapter for deterministic tests. Seed orders via `add_order`."""

    def __init__(self):
        self._orders: dict[str, _FakeOrder] = {}

    def add_order(self, **kwargs) -> _FakeOrder:
        order = _FakeOrder(**kwargs)
        self._orders[order.external_order_id] = order
        return order

    def discover_orders(
        self, status: str, job_type: str = "2D", limit: int = 40, cursor: str | None = None
    ) -> DiscoverResult:
        matched = [o for o in self._orders.values() if o.status == status]
        orders = [
            OrderSummary(
                external_order_id=o.external_order_id,
                product_name=o.product_name,
                designer=o.designer,
                status=o.status,
            )
            for o in matched[:limit]
        ]
        return DiscoverResult(success=True, orders=orders, cursor=None)

    def get_order_detail(self, external_order_id: str) -> OrderDetailResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return OrderDetailResult(success=False, error_class="VALIDATION")
        return OrderDetailResult(
            success=True,
            external_order_id=order.external_order_id,
            designer=order.designer,
            status=order.status,
            note_outsource=order.note_outsource,
            order_note=order.order_note,
            created_at=order.created_at,
            order_created_at=order.order_created_at,
            deadline_at=order.deadline_at,
            has_uploaded_design=order.has_uploaded_design,
        )

    def set_designer(self, external_order_id: str, designer_option: str) -> WriteResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return WriteResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        order.designer = designer_option
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"designer": order.designer},
        )

    def set_status(self, external_order_id: str, target_status: str) -> WriteResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return WriteResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        order.status = target_status
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"status": order.status},
        )

    def attach_result_link(self, external_order_id: str, drive_url: str) -> WriteResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return WriteResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        order.drive_url = drive_url
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"drive_url": order.drive_url},
        )

    def download_asset(self, external_order_id: str) -> AssetResult:
        order = self._orders.get(external_order_id)
        if order is None:
            return AssetResult(
                success=False, external_order_id=external_order_id, error_class="VALIDATION"
            )
        return AssetResult(
            success=True,
            external_order_id=external_order_id,
            local_path=f"/tmp/fake-assets/{external_order_id}.png",
            checksum="fakechecksum",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_printerval_fake_adapter.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/adapters/printerval/fake_adapter.py tests/test_printerval_fake_adapter.py
git commit -m "feat: in-memory FakePrintervalAdapter for deterministic tests"
```

---

### Task 4: Snapshot-restore smoke harness

**Files:**
- Create: `app/adapters/printerval/smoke_harness.py`
- Create: `scripts/printerval_smoke_test.py`
- Test: `tests/test_printerval_smoke_harness.py`

**Interfaces:**
- Consumes: `PrintervalAdapter` (Task 1, structural — works with any conforming adapter,
  fake or real), `FakePrintervalAdapter` (Task 3, for tests).
- Produces: `app.adapters.printerval.smoke_harness.OrderSnapshot`,
  `snapshot_order(adapter, external_order_id) -> OrderSnapshot`,
  `restore_order(adapter, snapshot) -> None` (raises `RuntimeError` if restore fails or
  doesn't verify), `run_write_method_smoke_test(adapter, external_order_id, action) -> None`
  where `action: Callable[[adapter, external_order_id], WriteResult]`. Tasks 5 and 6 use
  this module's functions via the CLI script when verifying real Playwright methods.

- [ ] **Step 1: Write the failing tests — `tests/test_printerval_smoke_harness.py`**

```python
import pytest

from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.adapters.printerval.smoke_harness import (
    restore_order,
    run_write_method_smoke_test,
    snapshot_order,
)


def _seeded_adapter():
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id="DJ0000001",
        product_name="Test product",
        designer="Nguyễn Thị Thuý Hường - 2D Prin",
        status="Doing",
    )
    return adapter


def test_snapshot_order_captures_current_state():
    adapter = _seeded_adapter()
    snapshot = snapshot_order(adapter, "DJ0000001")
    assert snapshot.designer == "Nguyễn Thị Thuý Hường - 2D Prin"
    assert snapshot.status == "Doing"


def test_restore_order_reverts_to_snapshot():
    adapter = _seeded_adapter()
    snapshot = snapshot_order(adapter, "DJ0000001")
    adapter.set_designer("DJ0000001", "Chưa chia cho ai")
    adapter.set_status("DJ0000001", "Waiting")

    restore_order(adapter, snapshot)

    detail = adapter.get_order_detail("DJ0000001")
    assert detail.designer == snapshot.designer
    assert detail.status == snapshot.status


def test_run_write_method_smoke_test_restores_after_action():
    adapter = _seeded_adapter()

    def action(adapter, order_id):
        return adapter.set_status(order_id, "Waiting")

    run_write_method_smoke_test(adapter, "DJ0000001", action)

    detail = adapter.get_order_detail("DJ0000001")
    assert detail.status == "Doing"  # restored, not left as "Waiting"


def test_run_write_method_smoke_test_still_restores_if_action_raises():
    adapter = _seeded_adapter()

    def action(adapter, order_id):
        adapter.set_status(order_id, "Waiting")
        raise RuntimeError("simulated failure mid-action")

    with pytest.raises(RuntimeError, match="simulated failure"):
        run_write_method_smoke_test(adapter, "DJ0000001", action)

    detail = adapter.get_order_detail("DJ0000001")
    assert detail.status == "Doing"  # still restored despite the raise


def test_snapshot_order_raises_for_unknown_order():
    adapter = _seeded_adapter()
    with pytest.raises(RuntimeError, match="Cannot snapshot"):
        snapshot_order(adapter, "DJ_NOPE")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_printerval_smoke_harness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.adapters.printerval.smoke_harness'`

- [ ] **Step 3: Create `app/adapters/printerval/smoke_harness.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.adapters.printerval.interface import PrintervalAdapter
from app.adapters.printerval.models import WriteResult


@dataclass
class OrderSnapshot:
    external_order_id: str
    designer: str | None
    status: str | None


def snapshot_order(adapter: PrintervalAdapter, external_order_id: str) -> OrderSnapshot:
    detail = adapter.get_order_detail(external_order_id)
    if not detail.success:
        raise RuntimeError(f"Cannot snapshot {external_order_id}: {detail.error_class}")
    return OrderSnapshot(
        external_order_id=external_order_id,
        designer=detail.designer,
        status=detail.status,
    )


def restore_order(adapter: PrintervalAdapter, snapshot: OrderSnapshot) -> None:
    errors: list[str] = []
    if snapshot.designer is not None:
        result = adapter.set_designer(snapshot.external_order_id, snapshot.designer)
        if not result.success:
            errors.append(f"restore designer failed: {result.error_class}")
    if snapshot.status is not None:
        result = adapter.set_status(snapshot.external_order_id, snapshot.status)
        if not result.success:
            errors.append(f"restore status failed: {result.error_class}")

    verify = snapshot_order(adapter, snapshot.external_order_id)
    if verify.designer != snapshot.designer or verify.status != snapshot.status:
        errors.append(
            f"restore verification mismatch: expected designer={snapshot.designer!r} "
            f"status={snapshot.status!r}, got designer={verify.designer!r} "
            f"status={verify.status!r}"
        )
    if errors:
        raise RuntimeError(
            f"RESTORE FAILED for {snapshot.external_order_id}: {'; '.join(errors)}. "
            "Manual intervention required — the order may be left in a modified state."
        )


def run_write_method_smoke_test(
    adapter: PrintervalAdapter,
    external_order_id: str,
    action: Callable[[PrintervalAdapter, str], WriteResult],
) -> None:
    """Run snapshot -> act -> verify -> restore -> verify-restore for one write method.

    `action(adapter, external_order_id)` performs the write under test and
    must return a WriteResult. Restore always runs, even if `action` raises.
    """
    snapshot = snapshot_order(adapter, external_order_id)
    try:
        result = action(adapter, external_order_id)
        if not result.success:
            raise RuntimeError(f"Action failed: {result.error_class}")
    finally:
        restore_order(adapter, snapshot)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_printerval_smoke_harness.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Create `scripts/printerval_smoke_test.py`** (thin CLI wrapper — not
      itself unit tested; it is the tool a human runs to verify a real write method,
      per Tasks 5/6)

```python
#!/usr/bin/env python3
"""
Manual, supervised smoke test for the real Playwright Printerval adapter.

NOT part of the pytest/CI suite. Run by hand when verifying a real write
method against production, per the safety rule in
docs/superpowers/specs/2026-09-07-phase2-adapter-design.md §1: every write
must snapshot -> act -> verify -> restore -> verify-restore.

Usage:
    python scripts/printerval_smoke_test.py DJ0000001 --method set_status --value Doing
"""
from __future__ import annotations

import argparse

from app.adapters.playwright_support import playwright_session
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter
from app.adapters.printerval.smoke_harness import run_write_method_smoke_test


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order_id", help="Mã đơn DJ####### để test")
    parser.add_argument(
        "--method",
        choices=["set_designer", "set_status", "attach_result_link"],
        required=True,
    )
    parser.add_argument(
        "--value", required=True, help="Giá trị mới để test (designer/status/drive_url)"
    )
    args = parser.parse_args()

    with playwright_session() as page:
        adapter = PlaywrightPrintervalAdapter(page)

        def action(adapter, order_id):
            method = getattr(adapter, args.method)
            return method(order_id, args.value)

        run_write_method_smoke_test(adapter, args.order_id, action)

    print(f"Smoke test PASSED for {args.method} on {args.order_id} — state restored.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add app/adapters/printerval/smoke_harness.py scripts/printerval_smoke_test.py tests/test_printerval_smoke_harness.py
git commit -m "feat: snapshot-restore smoke harness for safely testing real Printerval writes"
```

---

### Task 5: Real Playwright Printerval adapter — read methods

**Files:**
- Create: `app/adapters/printerval/playwright_adapter.py` (this task implements
  `discover_orders`, `get_order_detail`, `download_asset`; Task 6 adds the write methods
  to the same file)
- Modify: `.env.example` (add `PRINTERVAL_ADMIN_URL` placeholder — credentials
  themselves go in the untracked `.env`, never `.env.example`)

**Interfaces:**
- Consumes: `app.adapters.printerval.models.*`, `app.adapters.printerval.interface.PrintervalAdapter`
  (Task 1); `app.adapters.playwright_support.capture_evidence` (Task 2).
- Produces: `app.adapters.printerval.playwright_adapter.PlaywrightPrintervalAdapter`
  (constructor: `PlaywrightPrintervalAdapter(page)`) with the 3 read methods implemented
  against the real site. Task 6 adds the 3 write methods to this same class. Task 9's
  contract test constructs this class (with a dummy `page` object, no I/O) to check
  Protocol conformance.

**Before you start — prerequisite (one-time, manual, not a code step):** the Chrome
profile directory `chrome-profile/` (used by `playwright_session()` from Task 2) must
already be logged into Printerval. If it isn't yet, run:

```bash
python -c "
from app.adapters.playwright_support import playwright_session
with playwright_session(headless=False) as page:
    page.goto('https://printerval.com/central/outsource/pod/design-job/admin')
    input('Log in manually in the opened browser window, then press Enter here...')
"
```

Log in with the credentials from `.env` (`PRINTERVAL_USERNAME`/`PRINTERVAL_PASSWORD` —
same account used in the Phase 0 exploration). The session persists in `chrome-profile/`
(gitignored) for all future runs — this login step is not repeated by the adapter code.

- [ ] **Step 1: Add the admin URL placeholder to `.env.example`**

```
PRINTERVAL_ADMIN_URL=https://printerval.com/central/outsource/pod/design-job/admin
```

Add the real `PRINTERVAL_USERNAME`/`PRINTERVAL_PASSWORD` (used only for the one-time
manual login above, not read by adapter code) to your own untracked `.env` — do not add
placeholders for these to `.env.example` beyond a comment noting they're needed for the
one-time manual login.

- [ ] **Step 2: Create `app/adapters/printerval/playwright_adapter.py` with a selector
      helper and the 3 read methods**

The exact selectors below are a starting draft based on Phase 0's documented field map
(`docs/phase0-field-map.md`) and the site's known structure: each order row contains
exactly two `<select>` elements, always in this order — Designer first, then Status
(confirmed in Phase 0's DOM dump: `select_5`/`select_6` are Designer/Status for one row,
`select_7`/`select_8` the next row, and so on). **You must verify this against the live
site before trusting it** — Step 3 below is the mandatory live-verification step, not
optional polish.

```python
from __future__ import annotations

import hashlib
from pathlib import Path

from playwright.sync_api import Page

from app.adapters.playwright_support import capture_evidence
from app.adapters.printerval.models import (
    AssetResult,
    DiscoverResult,
    OrderDetailResult,
    OrderSummary,
    WriteResult,
)

ADMIN_URL = "https://printerval.com/central/outsource/pod/design-job/admin"


def _find_select_by_option_text(page: Page, expected_option_substring: str):
    """Locate a <select> by one of its option texts (stable — independent of
    position on the page, unlike an index-based selector)."""
    for select in page.locator("select").all():
        options_text = select.locator("option").all_inner_texts()
        if any(expected_option_substring in opt for opt in options_text):
            return select
    raise LookupError(
        f"No <select> found with an option containing {expected_option_substring!r}"
    )


def _row_for_order(page: Page, external_order_id: str):
    row = page.locator(f"tr:has-text('{external_order_id}')").first
    row.wait_for(state="visible", timeout=10_000)
    return row


class PlaywrightPrintervalAdapter:
    def __init__(self, page: Page):
        self.page = page

    def discover_orders(
        self,
        status: str,
        job_type: str = "2D",
        limit: int = 40,
        cursor: str | None = None,
    ) -> DiscoverResult:
        page = self.page
        page.goto(ADMIN_URL)
        try:
            status_select = _find_select_by_option_text(page, status)
            status_select.select_option(label=status)
            job_type_select = _find_select_by_option_text(page, job_type)
            job_type_select.select_option(label=job_type)
            page.get_by_role("button", name="Lọc").click()
            page.wait_for_load_state("networkidle")
        except Exception:
            evidence = capture_evidence(page, "discover_orders_filter_failed")
            return DiscoverResult(success=False, error_class="EXTERNAL_CHANGED", evidence=evidence)

        rows = page.locator("table tbody tr").all()
        orders: list[OrderSummary] = []
        for row in rows[:limit]:
            text = row.inner_text()
            order_id = next((tok for tok in text.split() if tok.startswith("DJ")), None)
            if order_id is None:
                continue
            selects = row.locator("select")
            designer_value = selects.nth(0).input_value() if selects.count() >= 1 else None
            status_value = selects.nth(1).input_value() if selects.count() >= 2 else status
            orders.append(
                OrderSummary(
                    external_order_id=order_id,
                    product_name=text.splitlines()[0] if text else "",
                    designer=designer_value,
                    status=status_value,
                )
            )
        return DiscoverResult(success=True, orders=orders, cursor=None)

    def get_order_detail(self, external_order_id: str) -> OrderDetailResult:
        page = self.page
        try:
            row = _row_for_order(page, external_order_id)
        except Exception:
            evidence = capture_evidence(page, f"get_order_detail_missing_{external_order_id}")
            return OrderDetailResult(success=False, error_class="VALIDATION", evidence=evidence)

        selects = row.locator("select")
        designer = selects.nth(0).input_value() if selects.count() >= 1 else None
        status = selects.nth(1).input_value() if selects.count() >= 2 else None
        return OrderDetailResult(
            success=True,
            external_order_id=external_order_id,
            designer=designer,
            status=status,
            has_uploaded_design=row.locator("img").count() > 0,
        )

    def download_asset(self, external_order_id: str) -> AssetResult:
        page = self.page
        row = _row_for_order(page, external_order_id)
        img = row.locator("img").first
        if img.count() == 0:
            return AssetResult(success=False, external_order_id=external_order_id, error_class="VALIDATION")
        src = img.get_attribute("src")
        response = page.request.get(src)
        Path("order_assets").mkdir(exist_ok=True)
        local_path = Path("order_assets") / f"{external_order_id}.png"
        local_path.write_bytes(response.body())
        checksum = hashlib.sha256(response.body()).hexdigest()
        return AssetResult(
            success=True,
            external_order_id=external_order_id,
            local_path=str(local_path),
            checksum=checksum,
        )
```

- [ ] **Step 3: Mandatory live verification (not automated — run this yourself, or as
      the implementing agent with the read-only permission already granted for this
      Phase)**

Pick one real order ID currently visible on the admin page (any status is fine — these
are read-only calls, nothing is modified). Run:

```bash
python -c "
from app.adapters.playwright_support import playwright_session
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter

with playwright_session() as page:
    adapter = PlaywrightPrintervalAdapter(page)
    result = adapter.discover_orders(status='Waiting')
    print('discover_orders:', result.success, len(result.orders), 'orders found')
    if result.orders:
        one_id = result.orders[0].external_order_id
        detail = adapter.get_order_detail(one_id)
        print('get_order_detail:', detail.success, detail.designer, detail.status)
        asset = adapter.download_asset(one_id)
        print('download_asset:', asset.success, asset.local_path)
"
```

Expected: `discover_orders` finds at least 1 order (there were 529 in the pipeline as of
the Phase 0 survey), `get_order_detail` returns a real designer/status string,
`download_asset` writes a real file under `order_assets/` and prints a path. **If any
selector doesn't match the live DOM, fix the selector in Step 2's code now** — this is
expected iteration, not a sign the plan is wrong. Record what you found and any selector
adjustments you made in your task report.

- [ ] **Step 4: Commit**

```bash
git add app/adapters/printerval/playwright_adapter.py .env.example
git commit -m "feat: real Playwright Printerval adapter — read methods (discover, detail, asset)"
```

---

### Task 6: Real Playwright Printerval adapter — write methods

**Files:**
- Modify: `app/adapters/printerval/playwright_adapter.py` (add `set_designer`,
  `set_status`, `attach_result_link` to the `PlaywrightPrintervalAdapter` class from
  Task 5)

**Interfaces:**
- Consumes: everything from Task 5's `PlaywrightPrintervalAdapter`; `capture_evidence`
  (Task 2); `run_write_method_smoke_test` + `scripts/printerval_smoke_test.py` (Task 4)
  for verification.
- Produces: the completed 6-method `PlaywrightPrintervalAdapter`, fully conforming to
  `PrintervalAdapter`.

- [ ] **Step 1: Add the 3 write methods to `PlaywrightPrintervalAdapter`**

Read-after-write verification is mandatory per claude.md §8: after selecting a new
option, re-read the same field and confirm it matches before returning `success=True`.
If it doesn't match, return `UNKNOWN_OUTCOME` rather than raising or silently returning
success.

```python
    def set_designer(self, external_order_id: str, designer_option: str) -> WriteResult:
        page = self.page
        row = _row_for_order(page, external_order_id)
        designer_select = row.locator("select").nth(0)
        designer_select.select_option(label=designer_option)
        observed = designer_select.input_value()
        if observed != designer_option:
            evidence = capture_evidence(page, f"set_designer_unverified_{external_order_id}")
            return WriteResult(
                success=False,
                external_order_id=external_order_id,
                error_class="UNKNOWN_OUTCOME",
                retryable=False,
                evidence=evidence,
                observed_state={"designer": observed},
            )
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"designer": observed},
        )

    def set_status(self, external_order_id: str, target_status: str) -> WriteResult:
        page = self.page
        row = _row_for_order(page, external_order_id)
        status_select = row.locator("select").nth(1)
        status_select.select_option(label=target_status)
        observed = status_select.input_value()
        if observed != target_status:
            evidence = capture_evidence(page, f"set_status_unverified_{external_order_id}")
            return WriteResult(
                success=False,
                external_order_id=external_order_id,
                error_class="UNKNOWN_OUTCOME",
                retryable=False,
                evidence=evidence,
                observed_state={"status": observed},
            )
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"status": observed},
        )

    def attach_result_link(self, external_order_id: str, drive_url: str) -> WriteResult:
        page = self.page
        row = _row_for_order(page, external_order_id)
        design_upload_area = row.locator("[class*=design], [class*=upload]").first
        if design_upload_area.count() == 0:
            evidence = capture_evidence(page, f"attach_result_link_no_area_{external_order_id}")
            return WriteResult(
                success=False,
                external_order_id=external_order_id,
                error_class="EXTERNAL_CHANGED",
                evidence=evidence,
            )
        # Exact interaction (file-link field vs upload button) must be confirmed
        # against the live DOM in Step 2 below — Phase 0's field map documents an
        # upload area ("+") and a "Xem template của job" link, but not a plain
        # URL-paste field; this may need adjusting once you see the real control.
        design_upload_area.fill(drive_url)
        return WriteResult(
            success=True,
            external_order_id=external_order_id,
            observed_state={"drive_url": drive_url},
        )
```

- [ ] **Step 2: Mandatory live verification using the snapshot-restore harness — one
      order per method, per the Global Constraints rule (prefer a `Done` order; use
      `waiting` for `set_designer` since claim only applies there)**

For `set_status` (safe to test on a `Done` order — pick any real `DJ#######` currently
`Done`):

```bash
python scripts/printerval_smoke_test.py DJ<real-done-order-id> --method set_status --value Review
```

Expected output ends with `Smoke test PASSED for set_status on DJ... — state restored.`
Confirm by re-running `get_order_detail` on that same order afterward that its status is
back to `Done`.

For `set_designer` (needs a `waiting` order — claim only applies to unclaimed orders):

```bash
python scripts/printerval_smoke_test.py DJ<real-waiting-order-id> --method set_designer --value "Nguyễn Thị Thuý Hường - 2D Prin"
```

For `attach_result_link` (a `Done` order is fine — this only edits a note assumed to
show the design/result link):

```bash
python scripts/printerval_smoke_test.py DJ<real-done-order-id> --method attach_result_link --value "https://drive.google.com/file/d/test/view"
```

If the harness raises `RESTORE FAILED`, **stop immediately, do not proceed to the next
method, and report the order ID + error in your task report** — this needs a human to
manually check and fix the live order before continuing. Record every real order ID used
and the harness's PASSED/FAILED output in your report.

- [ ] **Step 3: Adjust `attach_result_link`'s selector if Step 2 revealed a different
      real control** (e.g. an upload button instead of a text field) — this is expected;
      document what you found.

- [ ] **Step 4: Commit**

```bash
git add app/adapters/printerval/playwright_adapter.py
git commit -m "feat: real Playwright Printerval adapter — write methods (designer, status, result link)"
```

---

### Task 7: Fake Google Sheets/Drive adapters

**Files:**
- Create: `app/adapters/google/fake_sheets_adapter.py`
- Create: `app/adapters/google/fake_drive_adapter.py`
- Test: `tests/test_google_fake_adapters.py`

**Interfaces:**
- Consumes: `app.adapters.google.models.*` (Task 1).
- Produces: `FakeSheetsAdapter` (in-memory, `.rows_by_sheet: dict[str, list[dict]]`
  after calls), `FakeDriveAdapter` (constructor takes `known_file_ids: set[str]` to
  simulate which Drive file IDs "exist"). Task 9's contract tests use both.

- [ ] **Step 1: Write the failing tests — `tests/test_google_fake_adapters.py`**

```python
from datetime import datetime, timezone

from app.adapters.google.fake_drive_adapter import FakeDriveAdapter
from app.adapters.google.fake_sheets_adapter import FakeSheetsAdapter


def test_export_snapshot_appends_rows():
    adapter = FakeSheetsAdapter()
    result = adapter.export_snapshot(
        rows=[{"order_id": "DJ0000001", "status": "Done"}],
        sheet_id="sheet-abc",
        exported_at=datetime.now(timezone.utc),
    )
    assert result.success is True
    assert result.rows_written == 1
    assert adapter.rows_by_sheet["sheet-abc"] == [{"order_id": "DJ0000001", "status": "Done"}]


def test_export_snapshot_accumulates_across_calls():
    adapter = FakeSheetsAdapter()
    adapter.export_snapshot(rows=[{"a": 1}], sheet_id="s1", exported_at=datetime.now(timezone.utc))
    adapter.export_snapshot(rows=[{"a": 2}], sheet_id="s1", exported_at=datetime.now(timezone.utc))
    assert len(adapter.rows_by_sheet["s1"]) == 2


def test_export_snapshot_handles_empty_rows():
    adapter = FakeSheetsAdapter()
    result = adapter.export_snapshot(rows=[], sheet_id="s1", exported_at=datetime.now(timezone.utc))
    assert result.success is True
    assert result.rows_written == 0


def test_verify_url_recognizes_known_file():
    adapter = FakeDriveAdapter(known_file_ids={"abc123"})
    result = adapter.verify_url("https://drive.google.com/file/d/abc123/view")
    assert result.success is True
    assert result.exists is True
    assert result.accessible is True


def test_verify_url_flags_missing_file():
    adapter = FakeDriveAdapter(known_file_ids={"abc123"})
    result = adapter.verify_url("https://drive.google.com/file/d/notreal/view")
    assert result.success is True
    assert result.exists is False


def test_verify_url_rejects_malformed_url():
    adapter = FakeDriveAdapter(known_file_ids=set())
    result = adapter.verify_url("not-a-drive-url")
    assert result.success is False
    assert result.error_class == "VALIDATION"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_google_fake_adapters.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `app/adapters/google/fake_sheets_adapter.py`**

```python
from __future__ import annotations

from datetime import datetime

from app.adapters.google.models import ExportResult


class FakeSheetsAdapter:
    def __init__(self):
        self.rows_by_sheet: dict[str, list[dict]] = {}

    def export_snapshot(
        self, rows: list[dict], sheet_id: str, exported_at: datetime
    ) -> ExportResult:
        self.rows_by_sheet.setdefault(sheet_id, []).extend(rows)
        return ExportResult(success=True, rows_written=len(rows))
```

- [ ] **Step 4: Create `app/adapters/google/fake_drive_adapter.py`**

```python
from __future__ import annotations

import re

from app.adapters.google.models import DriveVerifyResult

_DRIVE_ID_PATTERN = re.compile(r"/d/([a-zA-Z0-9_-]+)")


class FakeDriveAdapter:
    def __init__(self, known_file_ids: set[str]):
        self._known_file_ids = known_file_ids

    def verify_url(self, drive_url: str) -> DriveVerifyResult:
        match = _DRIVE_ID_PATTERN.search(drive_url)
        if match is None:
            return DriveVerifyResult(success=False, error_class="VALIDATION")
        file_id = match.group(1)
        exists = file_id in self._known_file_ids
        return DriveVerifyResult(success=True, exists=exists, accessible=exists)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_google_fake_adapters.py -v`
Expected: all 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/adapters/google/fake_sheets_adapter.py app/adapters/google/fake_drive_adapter.py tests/test_google_fake_adapters.py
git commit -m "feat: in-memory fake Sheets/Drive adapters for deterministic tests"
```

---

### Task 8: Real Google Sheets/Drive adapters

**Files:**
- Modify: `pyproject.toml` (add `google-api-python-client`, `google-auth`)
- Create: `app/adapters/google/sheets_adapter.py`
- Create: `app/adapters/google/drive_adapter.py`
- Test: `tests/test_google_real_adapters.py`

**Interfaces:**
- Consumes: `app.adapters.google.models.*` (Task 1); the local credential file
  `credentials/google-service-account.json` (already present, gitignored — absent on
  CI, which is exactly what the skip guard below relies on).
- Produces: `GoogleSheetsAdapter(credentials_path: str = "credentials/google-service-account.json")`,
  `GoogleDriveAdapter(credentials_path: str = "credentials/google-service-account.json")`,
  both conforming to their respective Protocols from Task 1.

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

```toml
  "google-api-python-client>=2.140",
  "google-auth>=2.34",
```

Run: `pip install -e ".[dev]"`

- [ ] **Step 2: Create `app/adapters/google/sheets_adapter.py`**

```python
from __future__ import annotations

from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.adapters.google.models import ExportResult

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsAdapter:
    def __init__(self, credentials_path: str = "credentials/google-service-account.json"):
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        self._service = build("sheets", "v4", credentials=credentials)

    def export_snapshot(
        self, rows: list[dict], sheet_id: str, exported_at: datetime
    ) -> ExportResult:
        if not rows:
            return ExportResult(success=True, rows_written=0)
        values = [list(row.values()) for row in rows]
        try:
            response = (
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=sheet_id,
                    range="A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": values},
                )
                .execute()
            )
        except Exception:
            return ExportResult(success=False, error_class="TRANSIENT_NETWORK")
        updated = response.get("updates", {}).get("updatedRows", len(rows))
        return ExportResult(success=True, rows_written=updated)
```

- [ ] **Step 3: Create `app/adapters/google/drive_adapter.py`**

```python
from __future__ import annotations

import re

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.adapters.google.models import DriveVerifyResult

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

_DRIVE_ID_PATTERN = re.compile(r"/d/([a-zA-Z0-9_-]+)")


def _extract_file_id(drive_url: str) -> str | None:
    match = _DRIVE_ID_PATTERN.search(drive_url)
    if match:
        return match.group(1)
    if "id=" in drive_url:
        return drive_url.split("id=")[-1].split("&")[0]
    return None


class GoogleDriveAdapter:
    def __init__(self, credentials_path: str = "credentials/google-service-account.json"):
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        self._service = build("drive", "v3", credentials=credentials)

    def verify_url(self, drive_url: str) -> DriveVerifyResult:
        file_id = _extract_file_id(drive_url)
        if file_id is None:
            return DriveVerifyResult(success=False, exists=False, error_class="VALIDATION")
        try:
            self._service.files().get(fileId=file_id, fields="id,name").execute()
        except HttpError as exc:
            if exc.resp.status == 404:
                return DriveVerifyResult(success=True, exists=False, accessible=False)
            if exc.resp.status == 403:
                return DriveVerifyResult(success=True, exists=True, accessible=False)
            return DriveVerifyResult(success=False, error_class="TRANSIENT_NETWORK")
        return DriveVerifyResult(success=True, exists=True, accessible=True)
```

- [ ] **Step 4: Write the integration test — `tests/test_google_real_adapters.py`**

This test is real (hits the actual Google API) but fully self-contained: it creates its
own throwaway spreadsheet (owned by the service account) and deletes it afterward,
never touching any spreadsheet a human created. It auto-skips wherever the credential
file is absent (CI has none, by design).

```python
import os
from datetime import datetime, timezone

import pytest

CREDENTIALS_PATH = "credentials/google-service-account.json"

pytestmark = pytest.mark.skipif(
    not os.path.exists(CREDENTIALS_PATH),
    reason="No Google service account credential present (expected on CI)",
)


@pytest.fixture()
def temp_sheet():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sheets_credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    sheets_service = build("sheets", "v4", credentials=sheets_credentials)
    spreadsheet = (
        sheets_service.spreadsheets()
        .create(body={"properties": {"title": "pinterval-phase2-test-sheet"}})
        .execute()
    )
    sheet_id = spreadsheet["spreadsheetId"]

    yield sheet_id

    drive_credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH, scopes=["https://www.googleapis.com/auth/drive"]
    )
    drive_service = build("drive", "v3", credentials=drive_credentials)
    drive_service.files().delete(fileId=sheet_id).execute()


def test_export_snapshot_writes_rows_to_real_sheet(temp_sheet):
    from app.adapters.google.sheets_adapter import GoogleSheetsAdapter

    adapter = GoogleSheetsAdapter(credentials_path=CREDENTIALS_PATH)
    result = adapter.export_snapshot(
        rows=[{"order_id": "DJ0000001", "status": "Done"}],
        sheet_id=temp_sheet,
        exported_at=datetime.now(timezone.utc),
    )
    assert result.success is True
    assert result.rows_written == 1


def test_verify_url_detects_missing_file():
    from app.adapters.google.drive_adapter import GoogleDriveAdapter

    adapter = GoogleDriveAdapter(credentials_path=CREDENTIALS_PATH)
    result = adapter.verify_url("https://drive.google.com/file/d/nonexistent000000/view")
    assert result.success is True
    assert result.exists is False
```

- [ ] **Step 5: Run the test**

Run: `pytest tests/test_google_real_adapters.py -v`
Expected: both tests PASS (this machine has the credential file). Confirm in your report
that the temp spreadsheet was deleted (the fixture's teardown ran) — you can verify by
checking the service account has no leftover files:
`python -c "from google.oauth2 import service_account; from googleapiclient.discovery import build; c = service_account.Credentials.from_service_account_file('credentials/google-service-account.json', scopes=['https://www.googleapis.com/auth/drive']); s = build('drive','v3',credentials=c); print(s.files().list(q=\"name contains 'pinterval-phase2-test-sheet'\").execute())"`
— the `files` list should be empty after the test run.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/adapters/google/sheets_adapter.py app/adapters/google/drive_adapter.py tests/test_google_real_adapters.py
git commit -m "feat: real Google Sheets/Drive adapters + self-cleaning integration test"
```

---

### Task 9: Contract tests (Protocol conformance)

**Files:**
- Test: `tests/test_printerval_contract.py`
- Test: `tests/test_google_contract.py`

**Interfaces:**
- Consumes: `PrintervalAdapter`, `FakePrintervalAdapter`, `PlaywrightPrintervalAdapter`
  (Tasks 1, 3, 5/6); `SheetsAdapter`, `DriveAdapter`, `FakeSheetsAdapter`,
  `FakeDriveAdapter` (Task 1, 7); `GoogleSheetsAdapter`, `GoogleDriveAdapter` (Task 8).
- Produces: nothing new — this task only verifies every adapter implementation actually
  satisfies its declared `Protocol`, catching a fake/real drift immediately instead of at
  first real use.

- [ ] **Step 1: Write `tests/test_printerval_contract.py`**

```python
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.adapters.printerval.interface import PrintervalAdapter
from app.adapters.printerval.playwright_adapter import PlaywrightPrintervalAdapter


def test_fake_adapter_conforms_to_protocol():
    adapter = FakePrintervalAdapter()
    assert isinstance(adapter, PrintervalAdapter)


def test_playwright_adapter_conforms_to_protocol():
    # A dummy page object is enough — __init__ only stores it, no I/O happens here.
    adapter = PlaywrightPrintervalAdapter(page=object())
    assert isinstance(adapter, PrintervalAdapter)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_printerval_contract.py -v`
Expected: both tests PASS. If either fails, the corresponding adapter class is missing a
method the `Protocol` declares — fix the adapter, not this test.

- [ ] **Step 3: Write `tests/test_google_contract.py`**

Real adapter construction hits the network (`build(...)` fetches Google's API discovery
document) — mock both `Credentials.from_service_account_file` and `build` so this test
never touches the network, while still exercising the real class's actual `__init__` and
method-resolution path.

```python
from unittest.mock import patch

from app.adapters.google.drive_interface import DriveAdapter
from app.adapters.google.fake_drive_adapter import FakeDriveAdapter
from app.adapters.google.fake_sheets_adapter import FakeSheetsAdapter
from app.adapters.google.sheets_interface import SheetsAdapter


def test_fake_sheets_adapter_conforms_to_protocol():
    adapter = FakeSheetsAdapter()
    assert isinstance(adapter, SheetsAdapter)


def test_fake_drive_adapter_conforms_to_protocol():
    adapter = FakeDriveAdapter(known_file_ids=set())
    assert isinstance(adapter, DriveAdapter)


def test_real_sheets_adapter_conforms_to_protocol():
    with (
        patch("app.adapters.google.sheets_adapter.service_account.Credentials.from_service_account_file"),
        patch("app.adapters.google.sheets_adapter.build"),
    ):
        from app.adapters.google.sheets_adapter import GoogleSheetsAdapter

        adapter = GoogleSheetsAdapter(credentials_path="unused")
        assert isinstance(adapter, SheetsAdapter)


def test_real_drive_adapter_conforms_to_protocol():
    with (
        patch("app.adapters.google.drive_adapter.service_account.Credentials.from_service_account_file"),
        patch("app.adapters.google.drive_adapter.build"),
    ):
        from app.adapters.google.drive_adapter import GoogleDriveAdapter

        adapter = GoogleDriveAdapter(credentials_path="unused")
        assert isinstance(adapter, DriveAdapter)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_google_contract.py -v`
Expected: all 4 tests PASS, with zero network calls (both `Credentials` and `build` are
mocked).

- [ ] **Step 5: Run the full suite once**

Run: `pytest -v` and `ruff check .`
Expected: everything from Phase 1 (34 tests) plus this plan's new tests all PASS; ruff
clean (the one known `I001` on the autogenerated migration file is pre-existing and
already ignored via `per-file-ignores`, from Phase 1's final fix wave).

- [ ] **Step 6: Commit**

```bash
git add tests/test_printerval_contract.py tests/test_google_contract.py
git commit -m "test: contract tests ensuring fake/real adapters conform to their Protocols"
```

---

## Self-review notes

- **Spec coverage:** every section of `docs/superpowers/specs/2026-09-07-phase2-adapter-design.md`
  maps to a task — reliability package (Task 2), Printerval interface+errors (Task 1),
  fake adapter (Task 3), real adapter read/write split (Tasks 5, 6), snapshot-restore
  safety rule (Task 4, exercised in Task 6), Google Sheets/Drive fake+real (Tasks 7, 8),
  contract testing (Task 9).
- **Placeholder scan:** no TODO/TBD. Tasks 5 and 6 are explicit about which selectors are
  a verified-live-against-real-site starting draft rather than committed-blind code —
  this is a deliberate, concrete verification step (with a specified command and expected
  output), not a vague "handle appropriately."
- **Type consistency:** `PrintervalAdapter`'s 6 method signatures in Task 1 match every
  call site in Tasks 3, 5, 6, 9 exactly (parameter names, defaults, return types).
  `SheetsAdapter`/`DriveAdapter`'s single method each likewise match across Tasks 1, 7, 8,
  9.
- **Scope check:** this plan covers only the adapter layer (Phase 2). It deliberately
  does not wire adapters into a crawl job or Celery worker — that is Phase 3, a separate
  plan.
