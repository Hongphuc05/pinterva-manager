import uuid

from app.adapters.db.models import Batch, DeadLetter, Order, OrderAsset
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.application.crawl import claim_batch, discover_waiting_orders, import_claimed_batch
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


def test_import_claimed_batch_verifies_asset_and_transitions_state(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    batch_result = claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")

    result = import_claimed_batch(db_session, adapter, batch_result["batch_id"])

    assert result["imported"] == ["DJ0000001"]
    assert result["failed"] == []
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.CLAIMED_IMPORTED.value
    asset = db_session.query(OrderAsset).filter_by(order_id=order.id).one()
    assert asset.checksum == "fakechecksum"


def test_import_claimed_batch_leaves_order_discovered_on_download_failure(db_session, monkeypatch):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    batch_result = claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")

    def _fail(external_order_id):
        from app.adapters.printerval.models import AssetResult

        return AssetResult(
            success=False, external_order_id=external_order_id, error_class="VALIDATION"
        )

    monkeypatch.setattr(adapter, "download_asset", _fail)

    result = import_claimed_batch(db_session, adapter, batch_result["batch_id"])

    assert result["imported"] == []
    assert result["failed"] == ["DJ0000001"]
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.DISCOVERED.value
    assert db_session.query(OrderAsset).filter_by(order_id=order.id).count() == 0


def test_import_claimed_batch_only_retries_orders_still_missing_an_asset(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    batch_result = claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")
    import_claimed_batch(db_session, adapter, batch_result["batch_id"])

    calls = {"n": 0}
    original = adapter.download_asset

    def _counting(external_order_id):
        calls["n"] += 1
        return original(external_order_id)

    adapter.download_asset = _counting
    # Re-running import_claimed_batch on an already-fully-imported batch must not
    # re-call download_asset for an order that's no longer DISCOVERED — but since the
    # idempotency key is scoped to batch_id and the first call already completed, this
    # also proves the cached result short-circuits entirely.
    result = import_claimed_batch(db_session, adapter, batch_result["batch_id"])

    assert calls["n"] == 0
    assert result["imported"] == ["DJ0000001"]
