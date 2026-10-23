import pytest
from celery.exceptions import TimeoutError as CeleryTimeout
from kombu.exceptions import OperationalError

from config.celery import app as celery_app
from precisecapture.common.tasks import ping


def test_ping_round_trips_eagerly():
    # Test settings run tasks inline, so the whole suite never needs a broker.
    assert ping.delay().get() == "pong"


def test_celery_reads_django_settings():
    assert celery_app.conf.task_serializer == "json"
    assert ping.name == "common.ping"
    assert ping.name in celery_app.tasks


@pytest.mark.integration
def test_ping_round_trips_through_redis_and_a_worker(settings):
    """Needs the docker dev services: a real broker and an embedded worker."""
    settings.CELERY_TASK_ALWAYS_EAGER = False
    celery_app.conf.task_always_eager = False
    try:
        celery_app.connection_for_write().ensure_connection(max_retries=1)
    except OperationalError as exc:  # pragma: no cover
        pytest.fail(f"Redis broker not reachable at {celery_app.conf.broker_url}: {exc}")
    from celery.contrib.testing.worker import start_worker

    with start_worker(celery_app, perform_ping_check=False, loglevel="warning"):
        try:
            assert ping.delay().get(timeout=10) == "pong"
        except CeleryTimeout as exc:  # pragma: no cover
            pytest.fail(f"ping did not return within 10s: {exc}")
