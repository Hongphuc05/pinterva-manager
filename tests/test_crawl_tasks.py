from app.adapters.db.models import Order
from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.domain.models import OrderState
from app.workers.celery_app import celery_app
from app.workers.crawl_tasks import run_crawl_cycle


def test_celery_app_does_not_auto_claim_orders():
    schedule = celery_app.conf.beat_schedule
    # A crawl now happens only through the explicit API button.  Automatically
    # claiming a job assigned it to a hard-coded account and generated perpetual
    # retry dead-letters for platforms whose Designer list differs.
    assert "crawl-and-claim" not in schedule


def test_printerval_assignment_requests_use_the_priority_queue():
    route = celery_app.conf.task_routes[
        "app.workers.assignment_sync_tasks.sync_printerval_assignment_request"
    ]
    assert route["queue"] == "assignment"


def test_celery_app_has_status_sync_beat_schedule():
    schedule = celery_app.conf.beat_schedule
    assert "sync-order-statuses" in schedule
    entry = schedule["sync-order-statuses"]
    assert entry["task"] == "app.workers.status_sync_tasks.sync_order_statuses"
    assert entry["schedule"] == 300  # default STATUS_SYNC_INTERVAL_SECONDS


def test_run_crawl_cycle_discovers_claims_and_imports_in_order(db_session):
    adapter = FakePrintervalAdapter()
    adapter.add_order(
        external_order_id="DJ0000001",
        product_name="Test Mug",
        designer=None,
        status="Waiting",
    )

    summary = run_crawl_cycle(db_session, adapter, limit=40)

    assert summary["discovered"] == 1
    assert summary["claimed"] == 1
    assert summary["failed_claim"] == 0
    assert summary["imported"] == 1
    assert summary["failed_import"] == 0


def test_run_crawl_cycle_with_no_waiting_orders_is_a_no_op(db_session):
    adapter = FakePrintervalAdapter()

    summary = run_crawl_cycle(db_session, adapter, limit=40)

    assert summary == {
        "discovered": 0,
        "claimed": 0,
        "failed_claim": 0,
        "imported": 0,
        "failed_import": 0,
    }


def test_run_crawl_cycle_retries_an_order_whose_claim_previously_failed(db_session):
    """Regression test: a claim_batch failure used to strand an order at DISCOVERED
    forever — it already has an Order row, so the next cycle's discover step never
    treats it as "new" again, and nothing else ever retried the claim."""
    adapter = FakePrintervalAdapter()
    # Not added to the adapter yet -> set_designer fails VALIDATION on the first cycle.
    first = run_crawl_cycle(db_session, adapter, limit=40)
    assert first["discovered"] == 0  # nothing to discover from an empty fake adapter

    # Simulate the real scenario directly: an Order already sitting at DISCOVERED with
    # no successful claim (as claim_batch would leave it after a dead-lettered attempt).
    db_session.add(Order(external_order_id="DJ0000001", state=OrderState.DISCOVERED.value))
    db_session.commit()
    # Now the order becomes claimable on the real site.
    adapter.add_order(external_order_id="DJ0000001", product_name="Test Mug", designer=None, status="Waiting")

    second = run_crawl_cycle(db_session, adapter, limit=40)

    assert second["claimed"] == 1
    assert second["imported"] == 1
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.CLAIMED_IMPORTED.value


def test_run_crawl_cycle_actually_retries_a_claim_that_claim_batch_itself_already_failed(db_session):
    """Regression test (live incident 2026-09-08): once claim_batch itself has run and
    dead-lettered an order, that exact order_ids set is now a "completed" Operation —
    if a later cycle's retry re-used claim_batch's own idempotency key for the same
    still-unclaimed set (which is exactly what happens when nothing new is discovered
    in between), it silently returned the first cycle's cached failure forever and
    never actually asked the site again, so deadline/source fields (only populated by
    import_claimed_orders, gated on a confirmed claim) stayed empty indefinitely."""
    adapter = FakePrintervalAdapter()
    adapter.add_order(external_order_id="DJ0000001", product_name="Test Mug", designer=None, status="Waiting")

    # Cycle 1: discovered, but claim fails — simulate a real claim rejection.
    from app.adapters.printerval.models import WriteResult

    real_set_designer = adapter.set_designer
    adapter.set_designer = lambda *a, **k: WriteResult(success=False, external_order_id="DJ0000001", error_class="VALIDATION")
    first = run_crawl_cycle(db_session, adapter, limit=40)
    assert first["discovered"] == 1
    assert first["failed_claim"] == 1
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.DISCOVERED.value

    # Cycle 2: nothing new to discover (already has an Order row), site now accepts
    # the claim — must actually retry against the (fake) site, not return a cached
    # failure from cycle 1's already-"completed" claim_batch operation.
    adapter.set_designer = real_set_designer
    second = run_crawl_cycle(db_session, adapter, limit=40)
    assert second["discovered"] == 0
    assert second["claimed"] == 1
    assert second["imported"] == 1
    order = db_session.query(Order).filter_by(external_order_id="DJ0000001").one()
    assert order.state == OrderState.CLAIMED_IMPORTED.value

    # Cycle 3: already claimed+imported — nothing left to do.
    third = run_crawl_cycle(db_session, adapter, limit=40)
    assert third == {"discovered": 0, "claimed": 0, "failed_claim": 0, "imported": 0, "failed_import": 0}
