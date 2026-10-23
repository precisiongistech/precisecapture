from celery import shared_task


@shared_task(name="common.ping")
def ping() -> str:
    """Round-trip check for the worker and broker."""
    return "pong"
