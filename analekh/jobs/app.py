"""Celery app and beat schedule (design doc 9.2, 22.1).

Results and announcements are polled at the feeds' published 5-minute TTL; event feeds slower.
The universe refreshes weekly (UNIVERSE_REFRESH_CRON); background backfill runs nightly.
"""

from celery import Celery
from celery.schedules import crontab

from analekh.config import get_settings
from analekh.ingest.feeds import FEEDS

settings = get_settings()


def _cron(expr: str) -> crontab:
    minute, hour, day_of_month, month_of_year, day_of_week = expr.split()
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


app = Celery(
    "analekh", broker=settings.redis_url, backend=settings.redis_url, include=["analekh.jobs.tasks"]
)
app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=30,
    timezone="Asia/Kolkata",
    beat_schedule={
        **{
            f"poll-{name}": {
                "task": "analekh.jobs.tasks.poll_feed",
                "schedule": float(
                    settings.feed_poll_seconds
                    if cls == "fast"
                    else settings.event_feed_poll_seconds
                ),
                "args": (name,),
            }
            for name, (_, cls) in FEEDS.items()
        },
        "process-pending-items": {"task": "analekh.jobs.tasks.process_pending", "schedule": 120.0},
        "process-documents": {"task": "analekh.jobs.tasks.process_documents", "schedule": 600.0},
        "refresh-universe": {
            "task": "analekh.jobs.tasks.refresh_universe",
            "schedule": _cron(settings.universe_refresh_cron),
        },
        "background-backfill": {
            "task": "analekh.jobs.tasks.background_backfill",
            "schedule": crontab(minute=30, hour=1),
        },
    },
)
