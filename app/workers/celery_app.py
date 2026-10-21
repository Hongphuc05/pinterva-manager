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
        "app.workers.telegram_tasks",
        "app.workers.support_compare_tasks",
        "app.workers.printerval_chat_tasks",
    ],
)

# Writing a Designer/Status is a human-requested action and must never wait behind
# periodic crawl/status jobs. Review submission is more urgent than bulk Designer
# assignment: a Designer has already submitted work and Printerval must receive its
# link/status promptly. Redis priorities plus a prefetch of one prevent a solo
# assignment worker from reserving several bulk jobs ahead of that submission.
celery_app.conf.task_queues = (
    Queue("celery"),
    Queue("assignment", max_priority=10),
)
celery_app.conf.task_routes = {
    "app.workers.assignment_sync_tasks.sync_printerval_assignment_request": {
        "queue": "assignment"
    },
    "app.workers.assignment_sync_tasks.sync_order_review_to_printerval_task": {
        "queue": "assignment",
        "priority": 9,
    },
    "app.workers.assignment_sync_tasks.send_fix_dispute_task": {"queue": "assignment"},
    "app.workers.assignment_sync_tasks.sync_assignment_to_printerval_task": {
        "queue": "assignment"
    },
    "app.workers.sync_job_tasks.run_status_sync_job": {"queue": "celery"},
    "app.workers.order_sheet_backup_tasks.export_order_sheet_backup": {"queue": "celery"},
    "app.workers.support_compare_tasks.enqueue_support_compare_jobs": {"queue": "celery"},
    "app.workers.support_compare_tasks.notify_support_duplicate_candidates": {
        "queue": "celery"
    },
}
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.conf.task_track_started = True

celery_app.conf.timezone = _settings.celery_timezone


def build_beat_schedule(settings):
    schedule = {
        "check-designer-deadlines": {
            "task": "app.workers.telegram_tasks.check_designer_deadlines",
            "schedule": 60.0,
        },
        "reclaim-stale-sync-jobs": {
            "task": "app.workers.status_sync_tasks.reclaim_stale_sync_jobs",
            "schedule": 60.0,
        },
        "sync-order-statuses": {
            "task": "app.workers.status_sync_tasks.sync_order_statuses",
            "schedule": settings.status_sync_interval_seconds,
        },
        # Orders created in the last 7 days are refreshed twice an hour, the last
        # 60 days once a night at 02:00 (celery_timezone); older orders are not
        # synced automatically.  The active-feed sync continues every five minutes;
        # PlatformSyncState's lease keeps these read-only jobs from overlapping on
        # one platform.
        "sync-recent-order-statuses": {
            "task": "app.workers.status_sync_tasks.sync_recent_order_statuses",
            "schedule": crontab(minute="2,32"),
        },
        "sync-nightly-order-statuses": {
            "task": "app.workers.status_sync_tasks.sync_nightly_order_statuses",
            "schedule": crontab(hour=2, minute=0),
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
    if settings.support_compare_enabled:
        # Jobs are created only when Support confirms /check; this task just
        # delivers the local worker's report and the pairs Support selected.
        schedule["support-compare-telegram"] = {
            "task": "app.workers.support_compare_tasks.notify_support_duplicate_candidates",
            "schedule": 60.0,
        }
    return schedule


celery_app.conf.beat_schedule = build_beat_schedule(_settings)
