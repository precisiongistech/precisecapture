"""
Vector tiles (BUILD_PLAN M5 task 7, DECISIONS: Martin is internal only).

- `tiles_layer(z, x, y, query)` is a PostGIS function owned by pc_owner with EXECUTE granted to
  pc_tiles. Martin exposes it as a function source; it filters by project_id and layer_id from
  the query string and returns MVT. It is SECURITY DEFINER so Martin (NOBYPASSRLS, no tenant
  setting) can read features: the project/layer ids act as the capability, and only Django,
  after authenticating the user and checking membership, ever calls Martin.
- Django proxies GET /projects/{id}/tiles/{layer}/{z}/{x}/{y}.mvt to MARTIN_URL.
"""

import uuid

import httpx
from django.conf import settings

TILES_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION tiles_layer(z integer, x integer, y integer, query_params json)
RETURNS bytea
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
SECURITY DEFINER
AS $$
DECLARE
  p_project uuid := (query_params->>'project_id')::uuid;
  p_layer   uuid := (query_params->>'layer_id')::uuid;
  mvt bytea;
BEGIN
  IF p_project IS NULL OR p_layer IS NULL THEN
    RETURN NULL;
  END IF;
  SELECT INTO mvt ST_AsMVT(tile, 'features', 4096, 'geom') FROM (
    SELECT
      f.id::text AS id,
      f.status,
      f.version,
      f.area_m2,
      f.length_m,
      f.qa_flags::text AS qa_flags,
      f.attributes::text AS attributes,
      ST_AsMVTGeom(
        ST_Transform(f.geom, 3857),
        ST_TileEnvelope(z, x, y),
        4096, 64, true
      ) AS geom
    FROM features_feature f
    WHERE f.project_id = p_project AND f.layer_id = p_layer
      AND f.deleted = false AND f.geom IS NOT NULL
      AND f.geom && ST_Transform(ST_TileEnvelope(z, x, y), 4326)
  ) AS tile WHERE geom IS NOT NULL;
  RETURN mvt;
END
$$;
COMMENT ON FUNCTION tiles_layer IS 'PreciseCapture vector tiles filtered by project_id + layer_id.';
REVOKE ALL ON FUNCTION tiles_layer(integer, integer, integer, json) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION tiles_layer(integer, integer, integer, json) TO pc_app;
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'pc_tiles') THEN
    GRANT EXECUTE ON FUNCTION tiles_layer(integer, integer, integer, json) TO pc_tiles;
  END IF;
END $$;
"""

TILES_FUNCTION_REVERSE_SQL = "DROP FUNCTION IF EXISTS tiles_layer(integer, integer, integer, json);"


def martin_tile_url(project_id: uuid.UUID, layer_id: uuid.UUID, z: int, x: int, y: int) -> str:
    base = settings.MARTIN_URL.rstrip("/")
    return f"{base}/tiles_layer/{z}/{x}/{y}?project_id={project_id}&layer_id={layer_id}"


def fetch_tile(url: str) -> tuple[int, bytes, str]:
    """Return (status, body, content_type) from Martin. Network errors become 502."""
    try:
        resp = httpx.get(url, timeout=10.0)
    except httpx.HTTPError as exc:
        return 502, f"Tile server unavailable: {exc}".encode(), "text/plain"
    return (
        resp.status_code,
        resp.content,
        resp.headers.get("content-type", "application/vnd.mapbox-vector-tile"),
    )
