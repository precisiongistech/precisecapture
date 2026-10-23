"""Ninja router for the common app (mounted at the API root)."""

from django.http import HttpRequest
from ninja import Router
from ninja.responses import Status

from precisecapture.common import services
from precisecapture.common.schemas import HealthOut, WellKnownOut

router = Router(tags=["meta"])


@router.get("/health", response={200: HealthOut, 503: HealthOut}, auth=None, operation_id="health")
def health(request: HttpRequest) -> Status[dict[str, object]]:
    """Liveness and readiness: 200 when the database answers, 503 otherwise."""
    status, body = services.health_status()
    return Status(status, body)


@router.get(
    "/.well-known/precisecapture",
    response=WellKnownOut,
    auth=None,
    operation_id="wellKnown",
)
def well_known(request: HttpRequest) -> dict[str, object]:
    """Server discovery document (also served at the site root, RFC 8615 style)."""
    return services.well_known_document()
