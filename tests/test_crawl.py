import uuid

import pytest

from app.adapters.db.models import Batch, DeadLetter, Operation, Order, OrderAsset
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.adapters.printerval.models import OrderDetailResult
from app.application.crawl import (
    DiscoverFailedError,
    claim_batch,
    discover_waiting_orders,
    export_platform_orders_csv,
    find_unclaimed_order_ids,
    import_claimed_orders,
    refresh_order_detail,
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


def test_claim_batch_commits_after_every_order_not_once_for_the_whole_batch(db_session, monkeypatch):
    """Regression test: a big batch used to stay one uncommitted transaction from the
    first order to the last (each set_designer call is a real, possibly slow Playwright
    round-trip) — nothing about its progress was ever visible from outside, and one
    slow/stuck order looked identical to the whole request being hung. Each order must
    now commit on its own."""
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    _seed_waiting_order(adapter, "DJ0000002")
    _seed_waiting_order(adapter, "DJ0000003")

    commit_count = {"n": 0}
    original_commit = db_session.commit

    def _counting_commit():
        commit_count["n"] += 1
        original_commit()

    monkeypatch.setattr(db_session, "commit", _counting_commit)

    claim_batch(db_session, adapter, ["DJ0000001", "DJ0000002", "DJ0000003"], owner="ntth")

    # At least one commit per order, not one single commit for the entire batch.
    assert commit_count["n"] >= 3


def test_find_unclaimed_order_ids_returns_only_orders_with_no_confirmed_claim(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    # DJ0000002 intentionally not added to the adapter -> its claim will fail below.
    claim_batch(db_session, adapter, ["DJ0000001", "DJ0000002"], owner="ntth")

    unclaimed = find_unclaimed_order_ids(db_session, platform_id=None)

    assert unclaimed == ["DJ0000002"]


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

    def _fail(external_order_id, platform_id=None):
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


def test_import_claimed_orders_imports_without_asset_when_no_source_file_exists(db_session, monkeypatch):
    """Regression test: an order with no downloadable source file (download_asset
    succeeds with local_path=None — a plain product order) must still reach
    CLAIMED_IMPORTED via get_order_detail, just without an OrderAsset row."""
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001", thumbnail_url="https://assets.printerval.com/thumb.png")
    claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")

    def _no_asset(external_order_id, platform_id=None):
        from app.adapters.printerval.models import AssetResult

        return AssetResult(success=True, external_order_id=external_order_id, local_path=None)

    monkeypatch.setattr(adapter, "download_asset", _no_asset)

    result = import_claimed_orders(db_session, adapter)

    assert result["imported"] == ["DJ0000001"]
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.CLAIMED_IMPORTED.value
    assert order.thumbnail_url == "https://assets.printerval.com/thumb.png"
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


def test_claim_batch_idempotency_key_stays_within_column_limit_for_large_batches(db_session):
    """Regression test for a real production crash: a raw
    'claim_batch:DJ1,DJ2,...' key overflows operations.idempotency_key
    (VARCHAR(255)) once a real crawl discovers more than ~20 new orders at once
    (claude.md §16 notes up to 529 observed backlogged at one time)."""
    adapter = FakePrintervalAdapter()
    order_ids = [f"DJ{i:07d}" for i in range(1, 51)]  # 50 ids, well past the old overflow point
    for oid in order_ids:
        _seed_waiting_order(adapter, oid)

    claim_batch(db_session, adapter, order_ids, owner="ntth")

    op = db_session.query(Operation).filter_by(command_name="claim_batch").one()
    assert len(op.idempotency_key) <= 255


def test_import_claimed_orders_persists_order_detail_fields(db_session):
    from datetime import datetime

    from app.adapters.printerval.models import (
        CustomConfig,
        CustomConfigEntry,
        ProductSku,
        ProductVariant,
    )

    adapter = FakePrintervalAdapter()
    _seed_waiting_order(
        adapter,
        "DJ0000001",
        thumbnail_url="https://assets.printerval.com/thumb.webp",
        sku="P123-XL",
        product_category="Baseball Jerseys",
        product_variants=[ProductVariant(name="Size", value="XL")],
        product_skus=[ProductSku(
            sku="P123-XL",
            image_url="https://assets.printerval.com/sku-xl.webp",
            category="Baseball Jerseys",
            variants=[ProductVariant(name="Size", value="XL")],
        ).model_dump()],
        multiple_design=True,
        double_sided=False,
        priority_label="label label-default label-danger",
        created_at=datetime(2026, 9, 7, 3, 46),
        order_created_at=datetime(2026, 9, 7, 3, 38),
        deadline_at=datetime(2026, 9, 8, 3, 38, 52),
        note_outsource="some note",
        order_note="ebay url: https://example.com",
        custom_config=CustomConfig(
            original=[CustomConfigEntry(key="Your Name Here", value="Machado")],
            translated_vn=[CustomConfigEntry(key="Tên của Bạn", value="Machado")],
        ),
        design_tool_url="https://design-tool.printerval.com/?tab=design-job&code=Printerval-DJ0000001",
    )
    claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")

    result = import_claimed_orders(db_session, adapter)

    assert result["imported"] == ["DJ0000001"]
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.CLAIMED_IMPORTED.value
    assert order.thumbnail_url == "https://assets.printerval.com/thumb.webp"
    assert order.sku == "P123-XL"
    assert order.product_category == "Baseball Jerseys"
    assert order.product_variants == [{"name": "Size", "value": "XL"}]
    assert order.product_skus == [{
        "sku": "P123-XL",
        "image_url": "https://assets.printerval.com/sku-xl.webp",
        "category": "Baseball Jerseys",
        "variants": [{"name": "Size", "value": "XL"}],
        "custom_config": None,
    }]
    assert order.multiple_design is True
    assert order.double_sided is False
    assert order.priority_label == "label label-default label-danger"
    assert order.created_at_ext == datetime(2026, 9, 7, 3, 46)
    assert order.deadline_at_ext == datetime(2026, 9, 8, 3, 38, 52)
    assert order.note_outsource == "some note"
    assert order.custom_config == {
        "original": [{"key": "Your Name Here", "value": "Machado"}],
        "translated_vn": [{"key": "Tên của Bạn", "value": "Machado"}],
    }
    assert order.design_tool_url.startswith("https://design-tool.printerval.com")


def test_import_claimed_orders_dead_letters_on_get_order_detail_failure(db_session, monkeypatch):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001")
    claim_batch(db_session, adapter, ["DJ0000001"], owner="ntth")

    def _fail(external_order_id, platform_id=None):
        return OrderDetailResult(success=False, error_class="EXTERNAL_CHANGED")

    monkeypatch.setattr(adapter, "get_order_detail", _fail)

    result = import_claimed_orders(db_session, adapter)

    assert result["imported"] == []
    assert result["failed"] == ["DJ0000001"]
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.DISCOVERED.value, (
        "asset downloaded but detail missing must not reach CLAIMED_IMPORTED"
    )
    assert db_session.query(OrderAsset).filter_by(order_id=order.id).count() == 0, (
        "OrderAsset must not be written when detail extraction fails after it"
    )
    dead_letters = (
        db_session.query(DeadLetter)
        .filter_by(source="crawl.import_claimed_orders")
        .filter(DeadLetter.payload["stage"].astext == "get_order_detail")
        .all()
    )
    assert len(dead_letters) == 1


def test_export_platform_orders_csv_is_a_fresh_deduplicated_snapshot(db_session, monkeypatch, tmp_path):
    """Regression test: two orders, two calls — the CSV must always have exactly one
    row per order (no duplicate-on-retry like the old per-row append had), scoped to
    its own platform_id folder, auto-created on first use."""
    import app.application.crawl as crawl_module
    from app.adapters.db.models import Platform

    monkeypatch.setattr(crawl_module, "PLATFORM_DATA_DIR", tmp_path / "platform_data")

    platform = Platform(name="P export test", account_username="export_test@printerval.com")
    db_session.add(platform)
    db_session.flush()
    platform_id = platform.id
    db_session.add(Order(external_order_id="DJ0000001", state=OrderState.DISCOVERED.value, platform_id=platform_id))
    db_session.commit()

    path1 = export_platform_orders_csv(db_session, platform_id)
    path2 = export_platform_orders_csv(db_session, platform_id)

    assert path1 == path2
    assert path1 == tmp_path / "platform_data" / str(platform_id) / "orders.csv"
    rows = path1.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 2  # header + exactly one order row, even after two calls

    other_platform_dir = tmp_path / "platform_data" / str(uuid.uuid4())
    assert not other_platform_dir.exists()


def test_refresh_order_detail_picks_up_multiple_skus_added_after_the_original_import(db_session):
    """A refresh must replace the one-SKU snapshot when Printerval later exposes
    multiple sellable variants for the same design job."""
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000001", product_skus=[])
    order = Order(
        external_order_id="DJ0000001",
        state=OrderState.IN_PROGRESS.value,  # already past the one-time import step
        product_skus=None,
    )
    db_session.add(order)
    db_session.commit()

    adapter._orders["DJ0000001"].product_skus = [
        {"sku": "P123-XL", "category": "Shirts", "variants": [{"name": "Size", "value": "XL"}]},
        {"sku": "P123-2XL", "category": "Shirts", "variants": [{"name": "Size", "value": "2XL"}]},
    ]

    result = refresh_order_detail(db_session, adapter, order)

    assert result == {"success": True}
    assert order.state == OrderState.IN_PROGRESS.value  # never touched
    assert [item["sku"] for item in order.product_skus] == ["P123-XL", "P123-2XL"]


def test_refresh_order_detail_dead_letters_on_download_failure_without_touching_the_order(db_session):
    adapter = FakePrintervalAdapter()
    order = Order(external_order_id="DJ0000002", state=OrderState.IN_PROGRESS.value, product_name="Old Name")
    db_session.add(order)
    db_session.commit()
    # Never added to the adapter -> download_asset fails VALIDATION.

    result = refresh_order_detail(db_session, adapter, order)

    assert result == {"success": False, "stage": "get_order_detail"}
    assert order.product_name == "Old Name"
    dead_letters = db_session.query(DeadLetter).filter_by(source="crawl.refresh_order_detail").all()
    assert len(dead_letters) == 1
    assert dead_letters[0].payload["stage"] == "get_order_detail"


def test_refresh_order_detail_does_not_duplicate_the_asset_row_when_checksum_is_unchanged(db_session):
    adapter = FakePrintervalAdapter()
    _seed_waiting_order(adapter, "DJ0000003")
    order = Order(external_order_id="DJ0000003", state=OrderState.IN_PROGRESS.value)
    db_session.add(order)
    db_session.commit()

    refresh_order_detail(db_session, adapter, order)
    refresh_order_detail(db_session, adapter, order)  # nothing changed on the site

    assert db_session.query(OrderAsset).filter_by(order_id=order.id).count() == 1

    # Now the site's file genuinely changes -> a new OrderAsset row is recorded.
    adapter._orders["DJ0000003"].checksum = "a-different-checksum"
    refresh_order_detail(db_session, adapter, order)

    assert db_session.query(OrderAsset).filter_by(order_id=order.id).count() == 2
