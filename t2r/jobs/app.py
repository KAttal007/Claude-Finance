"""Celery app and beat schedule (design doc 7.1, 16.1).

Results and announcements are polled at the feeds' published 5-minute TTL; event feeds slower.
"""

from celery import Celery

from t2r.config import get_settings
from t2r.ingest.feeds import FEEDS

settings = get_settings()

app = Celery(
    "t2r", broker=settings.redis_url, backend=settings.redis_url, include=["t2r.jobs.tasks"]
)
app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=30,
    timezone="Asia/Kolkata",
    beat_schedule={
        **{
            f"poll-{name}": {
                "task": "t2r.jobs.tasks.poll_feed",
                "schedule": float(
                    settings.feed_poll_seconds
                    if cls == "fast"
                    else settings.event_feed_poll_seconds
                ),
                "args": (name,),
            }
            for name, (_, cls) in FEEDS.items()
        },
        "process-pending-items": {"task": "t2r.jobs.tasks.process_pending", "schedule": 120.0},
        "process-documents": {"task": "t2r.jobs.tasks.process_documents", "schedule": 600.0},
    },
)
