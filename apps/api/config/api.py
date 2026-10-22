"""The versioned Django Ninja API, mounted at /api/v1/."""

from ninja import NinjaAPI

from precisecapture.common.api import router as common_router
from precisecapture.common.errors import register_exception_handlers

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
