# Make sure the Celery app is always imported when Django starts, so @shared_task uses it.
from config.celery import app as celery_app

__all__ = ["celery_app"]
