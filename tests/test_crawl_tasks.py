from app.adapters.printerval.fake_adapter import FakePrintervalAdapter
from app.workers.celery_app import celery_app
from app.workers.crawl_tasks import run_crawl_cycle


def test_celery_app_has_crawl_beat_schedule():
    schedule = celery_app.conf.beat_schedule
    assert "crawl-and-claim" in schedule
    entry = schedule["crawl-and-claim"]
    assert entry["task"] == "app.workers.crawl_tasks.crawl_and_claim"
    assert entry["schedule"] == 300  # default CRAWL_INTERVAL_SECONDS from Task 1


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


def test_crawl_and_claim_task_logs_and_returns_without_db_writes_when_playwright_session_fails(
    monkeypatch, caplog
):
    from app.workers import crawl_tasks

    def _boom(*args, **kwargs):
        # playwright_session() itself must raise here, before any `with` block is
        # entered — NOT a generator (a generator function wouldn't run its body, and
        # thus wouldn't raise, until iterated as a context manager, which a plain
        # generator object doesn't support: `with cm:` would fail with AttributeError
        # on `__enter__` instead of propagating this RuntimeError).
        raise RuntimeError("Cloudflare/login not ready")

    monkeypatch.setattr(crawl_tasks, "playwright_session", _boom)

    with caplog.at_level("ERROR"):
        crawl_tasks.crawl_and_claim()

    assert "Cloudflare/login not ready" in caplog.text


def test_crawl_and_claim_logs_distinct_message_for_cycle_body_failure(monkeypatch, caplog):
    from contextlib import contextmanager

    from app.workers import crawl_tasks

    @contextmanager
    def _fake_session():
        yield object()

    monkeypatch.setattr(crawl_tasks, "playwright_session", _fake_session)

    def _boom_cycle(session, adapter, limit=40):
        raise RuntimeError("simulated bug inside run_crawl_cycle")

    monkeypatch.setattr(crawl_tasks, "run_crawl_cycle", _boom_cycle)

    with caplog.at_level("ERROR"):
        crawl_tasks.crawl_and_claim()

    assert "cycle raised an unexpected exception mid-run" in caplog.text
    assert "Playwright session failed to open" not in caplog.text
