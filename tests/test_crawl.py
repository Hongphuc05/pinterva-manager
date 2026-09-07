import uuid

import pytest

from app.adapters.db.models import Batch, DeadLetter, Order, OrderAsset
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.application.crawl import (
    DiscoverFailedError,
    claim_batch,
    discover_waiting_orders,
    import_claimed_orders,
)
from app.domain.models import OrderState


def _seed_waiting_order(adapter, external_order_id, **overrides):
    defaults = dict(
        external_order_id=external_order_id,
        product_name="Test Mug",
        designer=None,
        status="Waiting",
    )
    defaults.update(overrides)
    adapter.add_order(**defaults)


def test_discover_waiting_orders_returns_only_new_ids(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    _seed_waiting_order(adapter, "DJ0000002")
    db_session.add(Order(external_order_id="DJ0000001", state=OrderState.DISCOVERED.value))
    db_session.commit()

    new_ids = discover_waiting_orders(db_session, adapter, limit=40)

    assert new_ids == ["DJ0000002"]


def test_discover_waiting_orders_ignores_non_waiting_status(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001", status="Doing")

    new_ids = discover_waiting_orders(db_session, adapter, limit=40)

    assert new_ids == []


def test_claim_batch_creates_batch_and_order_rows_and_claims_on_adapter(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    _seed_waiting_order(adapter, "DJ0000002")

    result = claim_batch(db_session, adapter, ["DJ0000001", "DJ0000002"], owner="ntth")

    assert result["claimed"] == ["DJ0000001", "DJ0000002"]
    assert result["failed"] == []
    batch = db_session.query(Batch).filter_by(id=uuid.UUID(result["batch_id"])).one()
    assert batch.source == "printerval_crawl"
    assert batch.owner == "ntth"
    orders = db_session.query(Order).filter_by(batch_id=batch.id).all()
    assert {o.external_order_id for o in orders} == {"DJ0000001", "DJ0000002"}
    assert all(o.state == OrderState.DISCOVERED.value for o in orders)
    assert adapter.get_order_detail("DJ0000001").designer == "ntth"


def test_claim_batch_dead_letters_a_failing_order_without_aborting_the_batch(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    # DJ0000002 intentionally not added to the adapter -> set_designer will fail VALIDATION

    result = claim_batch(db_session, adapter, ["DJ0000001", "DJ0000002"], owner="ntth")

    assert result["claimed"] == ["DJ0000001"]
    assert result["failed"] == ["DJ0000002"]
    dead_letters = db_session.query(DeadLetter).filter_by(source="crawl.claim_batch").all()
    assert len(dead_letters) == 1
    assert dead_letters[0].payload["order_id"] == "DJ0000002"


def test_claim_batch_is_idempotent_for_the_same_order_ids(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")

    result1 = claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")
    result2 = claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")

    assert result1 == result2
    assert db_session.query(Batch).count() == 1


def test_import_claimed_orders_verifies_asset_and_transitions_state(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")

    result = import_claimed_orders(db_session, adapter)

    assert result["imported"] == ["DJ0000001"]
    assert result["failed"] == []
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.CLAIMED_IMPORTED.value
    asset = db_session.query(OrderAsset).filter_by(order_id=order.id).one()
    assert asset.checksum == "fakechecksum"


def test_import_claimed_orders_dead_letters_and_leaves_state_on_download_failure(
    db_session, monkeypatch
):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")

    def _fail(external_order_id):
        from app.adapters.printerval.models import AssetResult

        return AssetResult(
            success=False, external_order_id=external_order_id, error_class="VALIDATION"
        )

    monkeypatch.setattr(adapter, "download_asset", _fail)

    result = import_claimed_orders(db_session, adapter)

    assert result["imported"] == []
    assert result["failed"] == ["DJ0000001"]
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.DISCOVERED.value
    assert db_session.query(OrderAsset).filter_by(order_id=order.id).count() == 0


def test_import_claimed_orders_does_not_reimport_orders_already_imported(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")
    import_claimed_orders(db_session, adapter)  # first pass, succeeds

    calls = {"n": 0}
    original = adapter.download_asset

    def _counting(external_order_id):
        calls["n"] += 1
        return original(external_order_id)

    adapter.download_asset = _counting
    result = import_claimed_orders(db_session, adapter)  # second pass

    assert calls["n"] == 0  # already CLAIMED_IMPORTED, not selected by the query at all
    assert result["imported"] == []
    assert result["failed"] == []


def test_import_claimed_orders_excludes_orders_whose_claim_failed(db_session):
    """Finding 1 regression test: an order whose claim_batch attempt was
    dead-lettered (no confirmed-claim ExternalObservation) must never be picked up by
    import_claimed_orders, even though it sits at DISCOVERED exactly like a
    successfully-claimed order does."""
    adapter = FakePrintervalAdapter()
    # DJ0000001 is NOT added to the adapter -> claim_batch's set_designer call fails,
    # dead-letters it, but still creates the Order row (existing defensive behavior).
    claim_result = claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")
    assert claim_result["failed"] == ["DJ0000001"]
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.DISCOVERED.value

    # Now make DJ0000001 exist on the adapter with a downloadable asset — simulating
    # that, absent the fix, download_asset would have succeeded for this never-claimed
    # order.
    _seed_waiting_order(adapter, "DJ0000001", status="Waiting")

    result = import_claimed_orders(db_session, adapter)

    assert "DJ0000001" not in result["imported"]
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.DISCOVERED.value, (
        "a claim-failed order must never reach CLAIMED_IMPORTED"
    )


def test_import_claimed_orders_retries_a_crashed_attempt_on_next_call(db_session):
    """Finding 2 regression test: an order whose import operation was left mid-attempt
    (simulating a process crash — status stays 'pending' past its lease) must be
    retried on the next call, even though it's not part of any batch just created in
    that call."""
    import uuid
    from datetime import UTC, datetime, timedelta

    from app.application.operations import PENDING_LEASE

    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")

    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    # Manually insert a stale 'pending' Operation row for this order's import key,
    # simulating a crash mid-attempt on a PRIOR call to import_claimed_orders.
    from sqlalchemy import text

    db_session.execute(
        text(
            "INSERT INTO operations "
            "(id, idempotency_key, command_name, status, retry_count, created_at, updated_at) "
            "VALUES (:id, :key, 'import_order', 'pending', 0, :ts, :ts)"
        ),
        {
            "id": uuid.uuid4(),
            "key": f"import_order:{order.external_order_id}",
            "ts": datetime.now(UTC) - (PENDING_LEASE + timedelta(minutes=1)),
        },
    )
    db_session.commit()

    result = import_claimed_orders(db_session, adapter)

    assert result["imported"] == ["DJ0000001"]
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.CLAIMED_IMPORTED.value


def test_discover_waiting_orders_dead_letters_and_raises_on_failure(db_session, monkeypatch):
    """Must raise DiscoverFailedError, never silently return [] — a real incident
    showed a genuinely visible Waiting order on the live site get reported as "0 new
    orders" because this failure mode wasn't distinguished from "nothing new"."""
    adapter = FakePrintervalAdapter()

    def _fail(status, job_type="Tất cả 2D & 3D", limit=40, cursor=None):
        from app.adapters.printerval.models import DiscoverResult

        return DiscoverResult(success=False, error_class="EXTERNAL_CHANGED")

    monkeypatch.setattr(adapter, "discover_orders", _fail)

    with pytest.raises(DiscoverFailedError):
        discover_waiting_orders(db_session, adapter, limit=40)

    dead_letters = (
        db_session.query(DeadLetter).filter_by(source="crawl.discover_waiting_orders").all()
    )
    assert len(dead_letters) == 1
