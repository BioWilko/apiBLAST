from celery import Celery
from celery.schedules import crontab

from app.config import get_settings


def _make_celery() -> Celery:
    settings = get_settings()
    app = Celery("apiblast")
    app.config_from_object(
        {
            "broker_url": settings.REDIS_URL,
            "result_backend": settings.REDIS_URL,
            "task_serializer": "json",
            "result_serializer": "json",
            "accept_content": ["json"],
            "result_expires": 86_400,
            # Visibility timeout must exceed the longest expected BLAST job.
            # Redis re-delivers a task if the worker hasn't acked within this window.
            "broker_transport_options": {
                "visibility_timeout": 86_400,  # 24 hours
            },
            # Never prefetch more than 1 task — prevents a fast worker from hoarding
            # while a slow one is starved.
            "worker_prefetch_multiplier": 1,
            # Ack only after the task completes so that a killed worker causes
            # the task to be re-queued rather than silently lost.
            "task_acks_late": True,
            "task_reject_on_worker_lost": True,
            "worker_concurrency": settings.CELERY_CONCURRENCY,
            "task_soft_time_limit": settings.JOB_SOFT_TIMEOUT_S,
            "task_time_limit": settings.JOB_HARD_TIMEOUT_S,
            "task_track_started": True,
            "task_routes": {
                "app.tasks.blast.blast_run": {"queue": "blast"},
                "app.tasks.cleanup.expire_results": {"queue": "celery"},
            },
            "beat_schedule": {
                "expire-old-results": {
                    "task": "app.tasks.cleanup.expire_results",
                    "schedule": crontab(minute=0),  # top of every hour
                }
            },
        }
    )
    app.autodiscover_tasks(["app.tasks.blast", "app.tasks.cleanup"])
    return app


celery_app = _make_celery()
