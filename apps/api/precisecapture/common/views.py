"""
Plain Django views for the root-level endpoints (outside /api/v1).

They are `non_atomic_requests`: ATOMIC_REQUESTS would otherwise open a transaction for
every probe, and server discovery must work even when the database is down.
"""

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from precisecapture.common import services


@require_GET
@transaction.non_atomic_requests
def health(request: HttpRequest) -> JsonResponse:
    status, body = services.health_status()
    return JsonResponse(body, status=status)


@require_GET
@transaction.non_atomic_requests
def well_known(request: HttpRequest) -> JsonResponse:
    return JsonResponse(services.well_known_document())
