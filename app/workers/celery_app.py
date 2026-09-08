from __future__ import annotations

from celery import Celery

from app.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "pinterval_ops",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=[
        "app.workers.crawl_tasks",
        "app.workers.status_sync_tasks",
        "app.workers.assignment_sync_tasks",
    ],
)

celery_app.conf.beat_schedule = {
    "crawl-and-claim": {
        "task": "app.workers.crawl_tasks.crawl_and_claim",
        "schedule": _settings.crawl_interval_seconds,
    },
    "sync-order-statuses": {
        "task": "app.workers.status_sync_tasks.sync_order_statuses",
        "schedule": _settings.status_sync_interval_seconds,
    },
}
