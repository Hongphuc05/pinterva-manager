from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
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
        "app.workers.sync_job_tasks",
        "app.workers.assignment_sync_tasks",
        "app.workers.order_sheet_backup_tasks",
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
    "app.workers.assignment_sync_tasks.sync_order_review_to_printerval_task": {
        "queue": "assignment"
    },
    "app.workers.assignment_sync_tasks.sync_assignment_to_printerval_task": {
        "queue": "assignment"
    },
    "app.workers.sync_job_tasks.run_status_sync_job": {"queue": "celery"},
    "app.workers.order_sheet_backup_tasks.export_order_sheet_backup": {"queue": "celery"},
}

celery_app.conf.timezone = _settings.celery_timezone


def build_beat_schedule(settings):
    schedule = {
        "sync-order-statuses": {
            "task": "app.workers.status_sync_tasks.sync_order_statuses",
            "schedule": settings.status_sync_interval_seconds,
        },
    }
    if settings.order_sheet_backup_enabled:
        schedule["export-order-sheet-backup"] = {
            "task": "app.workers.order_sheet_backup_tasks.export_order_sheet_backup",
            "schedule": crontab(
                hour=settings.order_sheet_backup_hour,
                minute=settings.order_sheet_backup_minute,
            ),
        }
    return schedule


celery_app.conf.beat_schedule = build_beat_schedule(_settings)
