"""
Performance target (ENGINEERING_NOTES.md §7): bbox query over 100k features p95 < 500 ms.
Run manually: `uv run pytest -m perf tests/features/test_perf.py`.
"""

import random
import time
import uuid

import pytest
from django.db import connection

from precisecapture.common.tenancy import tenant_context
from precisecapture.features.models import Feature
from tests.factories import LayerFactory, OrganisationFactory, ProjectFactory

pytestmark = [pytest.mark.perf, pytest.mark.django_db(transaction=True)]

N = 100_000


def _seed(org, layer) -> None:
    rnd = random.Random(42)
    rows = []
    for _ in range(N):
        lon = -3.3 + rnd.random() * 1.1
        lat = 5.8 + rnd.random() * 1.1
        d = 0.0009
        ring = f"{lon} {lat},{lon + d} {lat},{lon + d} {lat + d},{lon} {lat + d},{lon} {lat}"
        wkt = f"SRID=4326;POLYGON(({ring}))"
        rows.append((str(uuid.uuid4()), str(org.id), str(layer.project_id), str(layer.id), wkt))
    with connection.cursor() as cur:
        cur.executemany(
            "INSERT INTO features_feature (id, org_id, project_id, layer_id, geometry_type, geom, "
            "attributes, schema_version, version, status, review_note, deleted, qa_flags, "
            "centroid_method, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 'polygon', ST_GeomFromEWKT(%s), '{}', 1, 1, 'submitted', '', "
            "false, '{}', '', now(), now())",
            rows,
        )
        cur.execute("ANALYZE features_feature")


def test_bbox_query_over_100k_features_is_fast():
    org = OrganisationFactory()
    with tenant_context(org.id):
        layer = LayerFactory(org=org, project=ProjectFactory(org=org), geometry_type="polygon")
        _seed(org, layer)
        timings = []
        for i in range(20):
            lon = -3.2 + (i % 10) * 0.1
            lat = 5.9 + (i // 10) * 0.5
            from django.contrib.gis.geos import Polygon

            bbox = Polygon.from_bbox((lon, lat, lon + 0.05, lat + 0.05))
            t0 = time.perf_counter()
            n = Feature.objects.filter(layer=layer, deleted=False, geom__bboverlaps=bbox).count()
            list(
                Feature.objects.filter(layer=layer, deleted=False, geom__bboverlaps=bbox).order_by(
                    "id"
                )[:500]
            )
            timings.append(time.perf_counter() - t0)
            assert n > 0
        timings.sort()
        p95 = timings[int(len(timings) * 0.95) - 1]
        median = timings[len(timings) // 2]
        report = f"bbox over {N} features: p95 {p95 * 1000:.0f} ms, median {median * 1000:.0f} ms"
        print(report)  # noqa: T201
        assert p95 < 0.5
