from django.conf import settings
from django.urls import path

from config.api import api
from precisecapture.common import views

urlpatterns = [
    path("api/v1/", api.urls),
    # Root endpoints outside the API prefix: load balancers probe /health, and the mobile app
    # discovers a server through /.well-known/precisecapture (RFC 8615 location).
    path("health", views.health, name="health"),
    path(".well-known/precisecapture", views.well_known, name="well-known"),
]

# Unknown paths and unhandled errors outside Ninja still answer with problem JSON.
handler404 = "precisecapture.common.errors.handler404"
handler500 = "precisecapture.common.errors.handler500"

if settings.PLATFORM_ADMIN_ENABLED:  # pragma: no cover - exercised manually, internal deployment
    from django.contrib import admin

    admin.site.site_header = f"{settings.INSTANCE_NAME} platform admin"
    urlpatterns.append(path("platform-admin/", admin.site.urls))
