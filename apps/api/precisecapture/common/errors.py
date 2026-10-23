"""
RFC 9457 problem JSON for every error the API returns.

One place turns exceptions into `application/problem+json`:

    {"type": "...", "title": "...", "status": 422, "detail": "...", "errors": [...]}

Raise `ProblemException` (or a subclass) from services and endpoints; Ninja's own
validation and auth errors, Django's 404/403 and unexpected exceptions are mapped too.
"""

import logging
from http import HTTPStatus
from typing import Any

from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError

log = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_TYPE_BASE = "https://precisecapture.app/problems/"


class ProblemException(Exception):
    """An error with a stable machine-readable `type` slug and an HTTP status."""

    status: int = 400
    slug: str = "bad-request"
    title: str = "Bad request"

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: list[dict[str, Any]] | None = None,
        status: int | None = None,
        slug: str | None = None,
        title: str | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = errors or []
        if status is not None:
            self.status = status
        if slug is not None:
            self.slug = slug
        if title is not None:
            self.title = title


class NotFound(ProblemException):
    status = 404
    slug = "not-found"
    title = "Not found"


class Unauthorized(ProblemException):
    status = 401
    slug = "unauthorized"
    title = "Unauthorized"


class Forbidden(ProblemException):
    status = 403
    slug = "forbidden"
    title = "Forbidden"


class Conflict(ProblemException):
    status = 409
    slug = "conflict"
    title = "Conflict"


class NotImplementedYet(ProblemException):
    status = 501
    slug = "not-implemented"
    title = "Not implemented"


class UnprocessableEntity(ProblemException):
    status = 422
    slug = "validation-failed"
    title = "Validation failed"


def problem_response(
    request: HttpRequest,
    *,
    status: int,
    title: str,
    slug: str = "about:blank",
    detail: str | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> HttpResponse:
    body: dict[str, Any] = {
        "type": "about:blank" if slug == "about:blank" else PROBLEM_TYPE_BASE + slug,
        "title": title,
        "status": status,
        "instance": request.path,
        "errors": errors or [],
    }
    if detail:
        body["detail"] = detail
    return JsonResponse(body, status=status, content_type=PROBLEM_CONTENT_TYPE)


def _ninja_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Map pydantic/Ninja error dicts to our `errors[]` shape, one entry per field."""
    out: list[dict[str, Any]] = []
    for err in exc.errors:
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path", "header")]
        out.append(
            {
                "field": ".".join(loc) or None,
                "code": str(err.get("type", "invalid")),
                "message": str(err.get("msg", "Invalid value")),
            }
        )
    return out


def register_exception_handlers(api: NinjaAPI) -> None:
    @api.exception_handler(ProblemException)
    def on_problem(request: HttpRequest, exc: ProblemException) -> HttpResponse:
        return problem_response(
            request,
            status=exc.status,
            title=exc.title,
            slug=exc.slug,
            detail=exc.detail,
            errors=exc.errors,
        )

    @api.exception_handler(ValidationError)
    def on_validation(request: HttpRequest, exc: ValidationError) -> HttpResponse:
        return problem_response(
            request,
            status=422,
            title="Validation failed",
            slug="validation-failed",
            detail="One or more fields are invalid.",
            errors=_ninja_validation_errors(exc),
        )

    @api.exception_handler(AuthenticationError)
    def on_auth(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
        return problem_response(
            request, status=401, title="Unauthorized", slug="unauthorized", detail=str(exc) or None
        )

    @api.exception_handler(HttpError)
    def on_http_error(request: HttpRequest, exc: HttpError) -> HttpResponse:
        return problem_response(
            request, status=exc.status_code, title=_title_for(exc.status_code), detail=str(exc)
        )

    @api.exception_handler(Http404)
    @api.exception_handler(ObjectDoesNotExist)
    def on_404(request: HttpRequest, exc: Exception) -> HttpResponse:
        return problem_response(request, status=404, title="Not found", slug="not-found")

    @api.exception_handler(PermissionDenied)
    def on_403(request: HttpRequest, exc: Exception) -> HttpResponse:
        return problem_response(request, status=403, title="Forbidden", slug="forbidden")

    @api.exception_handler(Exception)
    def on_unhandled(request: HttpRequest, exc: Exception) -> HttpResponse:
        # Never leak a stack trace to clients. The traceback goes to the log (and Sentry later).
        log.exception("Unhandled error on %s %s", request.method, request.path)
        return problem_response(
            request,
            status=500,
            title=_title_for(500),
            slug="internal-error",
            detail="Something went wrong on our side. The error has been logged.",
        )


def _title_for(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Error"


# --- Django-level handlers (routes Ninja never sees, e.g. an unknown path) -----------------


def handler404(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return problem_response(request, status=404, title=_title_for(404), slug="not-found")


def handler500(request: HttpRequest) -> HttpResponse:
    return problem_response(
        request,
        status=500,
        title=_title_for(500),
        slug="internal-error",
        detail="Something went wrong on our side. The error has been logged.",
    )
