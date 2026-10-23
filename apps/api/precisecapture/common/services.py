"""Business logic for the common app (health, server discovery)."""

from typing import Any

from django.conf import settings
from django.db import DatabaseError, connections

from precisecapture import __version__


def health_status() -> tuple[int, dict[str, Any]]:
    """Return (http_status, body). The database must answer for the service to be healthy."""
    checks: dict[str, str] = {}
    try:
        with connections["default"].cursor() as cur:
            cur.execute("SELECT 1")
        checks["database"] = "ok"
    except DatabaseError as exc:  # pragma: no cover - exercised by monkeypatching in tests
        checks["database"] = f"error: {exc.__class__.__name__}"
    healthy = all(v == "ok" for v in checks.values())
    return (
        200 if healthy else 503,
        {"status": "ok" if healthy else "degraded", "version": __version__, "checks": checks},
    )


def well_known_document() -> dict[str, Any]:
    """What a mobile app reads before login to check compatibility and show branding."""
    return {
        "name": settings.INSTANCE_NAME,
        "logo_url": settings.INSTANCE_LOGO_URL,
        "api_version": settings.API_VERSION,
        "min_app_version": settings.MIN_APP_VERSION,
        "auth_methods": list(settings.AUTH_METHODS),
        "api_base_url": settings.PUBLIC_BASE_URL.rstrip("/") + "/api/v1",
    }
