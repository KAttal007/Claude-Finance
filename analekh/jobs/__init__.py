"""Celery app; run with ``celery -A analekh.jobs worker`` (design doc Appendix D)."""

from analekh.jobs.app import app

__all__ = ["app"]
