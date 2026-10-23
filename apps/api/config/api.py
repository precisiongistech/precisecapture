"""The versioned Django Ninja API, mounted at /api/v1/."""

from ninja import NinjaAPI

from precisecapture.accounts.api import auth_router, devices_router, me_router
from precisecapture.common.api import router as common_router
from precisecapture.common.errors import register_exception_handlers
from precisecapture.orgs.api import invitations_router, orgs_router
from precisecapture.projects.api import layers_router, projects_router, templates_router

api = NinjaAPI(
    title="PreciseCapture API",
    version="1.0.0",
    description="GIS field data collection platform. Geometry on the wire is GeoJSON in "
    "EPSG:4326; errors are RFC 9457 problem JSON; timestamps are ISO 8601 UTC.",
    docs_url="/docs",
    openapi_url="/openapi.json",
    urls_namespace="api-v1",
)
register_exception_handlers(api)

api.add_router("", common_router)
api.add_router("/auth", auth_router)
api.add_router("/me", me_router)
api.add_router("/devices", devices_router)
api.add_router("/orgs", orgs_router)
api.add_router("/invitations", invitations_router)
api.add_router("/projects", projects_router)
api.add_router("/layers", layers_router)
api.add_router("/layer-templates", templates_router)
