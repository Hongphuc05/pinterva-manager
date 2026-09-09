from __future__ import annotations

from celery import Celery
from kombu import Queue

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

# Writing a Designer/Status is a human-requested action and must never wait behind
# periodic crawl/status jobs.  A normal worker consumes both queues; deployments may
# also run a dedicated ``-Q assignment`` worker when write volume grows.
celery_app.conf.task_queues = (Queue("celery"), Queue("assignment"))
celery_app.conf.task_routes = {
    "app.workers.assignment_sync_tasks.sync_printerval_assignment_request": {
        "queue": "assignment"
    },
}

celery_app.conf.beat_schedule = {
    "sync-order-statuses": {
        "task": "app.workers.status_sync_tasks.sync_order_statuses",
        "schedule": _settings.status_sync_interval_seconds,
    },
}
