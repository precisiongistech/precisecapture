"""The tiles_layer() PostGIS function returns MVT for one layer and nothing for other ids."""

import json
import uuid

import pytest
from django.db import connection

from precisecapture.common.tenancy import tenant_context
from precisecapture.features.geometry import parse_geometry
from tests.factories import FeatureFactory, LayerFactory, OrganisationFactory, ProjectFactory

pytestmark = pytest.mark.django_db

LAT, LON = 6.33, -2.83
D = 100 / 110_574


def _tile(z: int, x: int, y: int, project_id: uuid.UUID, layer_id: uuid.UUID) -> bytes | None:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT tiles_layer(%s, %s, %s, %s::json)",
            [z, x, y, json.dumps({"project_id": str(project_id), "layer_id": str(layer_id)})],
        )
        row = cur.fetchone()
    return bytes(row[0]) if row and row[0] is not None else None


def _tile_for(lon: float, lat: float, z: int) -> tuple[int, int]:
    import math

    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int(
        (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi)
        / 2
        * n
    )
    return x, y


def test_function_exists_and_is_executable_by_the_app_and_tiles_roles():
    with connection.cursor() as cur:
        sig = "tiles_layer(integer,integer,integer,json)"
        cur.execute("SELECT has_function_privilege('pc_app', %s, 'EXECUTE')", [sig])
        assert cur.fetchone()[0] is True
        cur.execute("SELECT has_function_privilege('pc_tiles', %s, 'EXECUTE')", [sig])
        assert cur.fetchone()[0] is True
        cur.execute("SELECT prosecdef FROM pg_proc WHERE proname = 'tiles_layer'")
        assert cur.fetchone()[0] is True  # SECURITY DEFINER: Martin needs no tenant setting


def test_tile_contains_the_layers_features_only():
    org = OrganisationFactory()
    with tenant_context(org.id):
        project = ProjectFactory(org=org)
        farms = LayerFactory(org=org, project=project, geometry_type="polygon", key="lyr_farms")
        other = LayerFactory(org=org, project=project, geometry_type="polygon", key="lyr_other")
        FeatureFactory(
            org=org,
            layer=farms,
            geom=parse_geometry(
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[LON, LAT], [LON + D, LAT], [LON + D, LAT + D], [LON, LAT + D], [LON, LAT]]
                    ],
                }
            ),
        )
        FeatureFactory(
            org=org,
            layer=farms,
            geom=parse_geometry(
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[LON, LAT], [LON + D, LAT], [LON + D, LAT + D], [LON, LAT + D], [LON, LAT]]
                    ],
                }
            ),
            deleted=True,
        )
        FeatureFactory(
            org=org,
            layer=other,
            geom=parse_geometry(
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[LON, LAT], [LON + D, LAT], [LON + D, LAT + D], [LON, LAT + D], [LON, LAT]]
                    ],
                }
            ),
        )
    x, y = _tile_for(LON + D / 2, LAT + D / 2, 14)
    # Called without any tenant context, as Martin would.
    mvt = _tile(14, x, y, project.id, farms.id)
    assert mvt is not None and len(mvt) > 20
    assert b"features" in mvt  # the MVT layer name
    assert _tile(14, x, y, project.id, other.id) is not None
    assert _tile(14, x, y, uuid.uuid4(), farms.id) in (None, b"")  # wrong project: nothing
    assert _tile(14, x + 50, y + 50, project.id, farms.id) in (None, b"")  # empty tile
    with connection.cursor() as cur:
        cur.execute("SELECT tiles_layer(14, %s, %s, '{}'::json)", [x, y])
        assert cur.fetchone()[0] is None  # no ids: nothing
