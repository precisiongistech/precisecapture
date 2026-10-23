import hashlib
import json
from collections.abc import Callable
from datetime import timedelta

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

from precisecapture.common.tenancy import clear_tenant

IDEMPOTENCY_TTL = timedelta(hours=24)
IDEMPOTENT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class TenantContextResetMiddleware:
    """Ensure no tenant leaks from one request to the next on a reused worker thread."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        clear_tenant()
        try:
            return self.get_response(request)
        finally:
            clear_tenant()


class IdempotencyMiddleware:
    """
    Honour `Idempotency-Key` on non-sync API writes: the first response for (user, key, method,
    path) is stored for 24 hours and replayed. The same key with a different body is a 422.
    Sync endpoints are excluded (they are idempotent on change_id).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        key = request.headers.get("Idempotency-Key")
        if (
            not key
            or request.method not in IDEMPOTENT_METHODS
            or not request.path.startswith("/api/v1/")
            or request.path.startswith("/api/v1/sync/")
        ):
            return self.get_response(request)
        user_id = _user_id_from_bearer(request)
        if user_id is None:
            return self.get_response(request)
        from precisecapture.common.models import IdempotencyKey

        body_hash = hashlib.sha256(request.body).hexdigest()
        cutoff = timezone.now() - IDEMPOTENCY_TTL
        stored = IdempotencyKey.objects.filter(
            user_id=user_id,
            key=key[:200],
            method=request.method,
            path=request.path,
            created_at__gte=cutoff,
        ).first()
        if stored is not None:
            if stored.request_hash != body_hash:
                return JsonResponse(
                    {
                        "type": "https://precisecapture.app/problems/idempotency-mismatch",
                        "title": "Idempotency key reused with a different request",
                        "status": 422,
                        "instance": request.path,
                        "errors": [],
                    },
                    status=422,
                    content_type="application/problem+json",
                )
            replay = HttpResponse(
                stored.response_body, status=stored.status_code, content_type="application/json"
            )
            replay["Idempotent-Replayed"] = "true"
            return replay
        response = self.get_response(request)
        if response.status_code < 500 and not response.streaming:
            IdempotencyKey.objects.get_or_create(
                user_id=user_id,
                key=key[:200],
                method=request.method,
                path=request.path,
                defaults={
                    "request_hash": body_hash,
                    "status_code": response.status_code,
                    "response_body": response.content.decode("utf-8", errors="replace"),
                },
            )
        return response


def _user_id_from_bearer(request: HttpRequest) -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    from precisecapture.accounts.tokens import verify_access_token
    from precisecapture.common.errors import Unauthorized

    try:
        return str(verify_access_token(header.removeprefix("Bearer ").strip()).user_id)
    except Unauthorized:
        return None


_ = json
