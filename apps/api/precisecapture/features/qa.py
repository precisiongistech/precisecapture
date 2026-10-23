"""
Overlap QA (ENGINEERING_NOTES.md §3): a polygon overlaps another non-deleted feature of the
same layer when ST_Intersects AND NOT ST_Touches, ignoring slivers below the tolerance.
The capture profile decides whether an overlap is flagged (default) or blocks the write.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from django.contrib.gis.geos import GEOSGeometry
from django.db import connection

from precisecapture.common.schema_validation import SchemaIssue

DEFAULT_TOLERANCE_SQM = 1.0


@dataclass(frozen=True)
class Overlap:
    feature_id: uuid.UUID
    area_m2: float


def find_overlaps(
    *,
    layer_id: uuid.UUID,
    org_id: uuid.UUID,
    geom: GEOSGeometry,
    exclude_feature_id: uuid.UUID | None,
    tolerance_sqm: float,
) -> list[Overlap]:
    """Other polygons in the layer whose overlap with `geom` exceeds the tolerance."""
    with connection.cursor() as cur:
        cur.execute(
            """
            WITH g AS (SELECT ST_GeomFromEWKB(%s) AS geom)
            SELECT f.id,
                   ST_Area(ST_Intersection(f.geom, g.geom)::geography) AS overlap_m2
            FROM features_feature f, g
            WHERE f.layer_id = %s AND f.org_id = %s AND f.deleted = false
              AND f.geom IS NOT NULL
              AND (%s IS NULL OR f.id <> %s)
              AND f.geom && g.geom
              AND ST_Intersects(f.geom, g.geom) AND NOT ST_Touches(f.geom, g.geom)
            """,
            [bytes(geom.ewkb), str(layer_id), str(org_id), exclude_feature_id, exclude_feature_id],
        )
        rows = cur.fetchall()
    return [
        Overlap(uuid.UUID(str(fid)), float(area))
        for fid, area in rows
        if float(area) > tolerance_sqm
    ]


def overlap_rules(profile: dict[str, Any]) -> tuple[bool, str, float]:
    """(check self overlaps?, 'flag' | 'block', tolerance m²) from the resolved profile."""
    topology = (profile.get("validation") or {}).get("topology") or {}
    targets = topology.get("noOverlapWith") or []
    on_overlap = topology.get("onOverlap") or "flag"
    tolerance = topology.get("overlapToleranceSqm")
    return (
        "self" in targets,
        str(on_overlap),
        float(tolerance) if tolerance is not None else DEFAULT_TOLERANCE_SQM,
    )


def check_overlaps(
    *,
    layer_id: uuid.UUID,
    org_id: uuid.UUID,
    geom: GEOSGeometry | None,
    exclude_feature_id: uuid.UUID | None,
    profile: dict[str, Any],
) -> tuple[list[SchemaIssue], list[str], list[Overlap]]:
    """Returns (rejections, qa flags, overlaps found)."""
    if geom is None or geom.geom_type not in ("Polygon", "MultiPolygon"):
        return [], [], []
    enabled, mode, tolerance = overlap_rules(profile)
    if not enabled:
        return [], [], []
    overlaps = find_overlaps(
        layer_id=layer_id,
        org_id=org_id,
        geom=geom,
        exclude_feature_id=exclude_feature_id,
        tolerance_sqm=tolerance,
    )
    if not overlaps:
        return [], [], []
    if mode == "block":
        ids = ", ".join(str(o.feature_id) for o in overlaps[:5])
        return (
            [
                SchemaIssue(
                    "geom", "overlap", f"Overlaps {len(overlaps)} existing feature(s): {ids}"
                )
            ],
            [],
            overlaps,
        )
    return [], ["overlap"], overlaps
