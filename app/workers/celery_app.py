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
        "app.workers.sync_job_tasks",
        "app.workers.assignment_sync_tasks",
        "app.workers.order_sheet_backup_tasks",
        "app.workers.telegram_tasks",
    ],
)

# Writing a Designer/Status is a human-requested action and must never wait behind
# periodic crawl/status jobs. Review submission is more urgent than bulk Designer
# assignment: a Designer has already submitted work and Printerval must receive its
# link/status promptly. Redis priorities plus a prefetch of one prevent a solo
# assignment worker from reserving several bulk jobs ahead of that submission.
celery_app.conf.task_queues = (Queue("celery"), Queue("assignment", max_priority=10))
celery_app.conf.task_routes = {
    "app.workers.assignment_sync_tasks.sync_printerval_assignment_request": {
        "queue": "assignment"
    },
    "app.workers.assignment_sync_tasks.sync_order_review_to_printerval_task": {
        "queue": "assignment",
        "priority": 9,
    },
    "app.workers.assignment_sync_tasks.sync_assignment_to_printerval_task": {
        "queue": "assignment"
    },
    "app.workers.sync_job_tasks.run_status_sync_job": {"queue": "celery"},
    "app.workers.order_sheet_backup_tasks.export_order_sheet_backup": {"queue": "celery"},
}
celery_app.conf.worker_prefetch_multiplier = 1

celery_app.conf.timezone = _settings.celery_timezone


def build_beat_schedule(settings):
    schedule = {
        "check-designer-deadlines": {
            "task": "app.workers.telegram_tasks.check_designer_deadlines",
            "schedule": 60.0,
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
