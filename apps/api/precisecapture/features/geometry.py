"""
Geometry validation and the server-computed measures (ENGINEERING_NOTES.md §3).

Everything metric is computed by PostGIS on the geography type in one query, so the web,
sync and tests all get identical numbers. Validation rules come from the resolved capture
profile; results are issues (problem-JSON error entries) and QA flags, never exceptions.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.db import connection

from precisecapture.common.schema_validation import SchemaIssue

ALLOWED_TYPES: dict[str, set[str]] = {
    "point": {"Point"},
    "line": {"LineString"},
    "polygon": {"Polygon", "MultiPolygon"},
    "none": set(),
}


@dataclass
class Measures:
    area_m2: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None
    centroid: GEOSGeometry | None = None
    centroid_method: str = ""
    is_valid: bool = True
    valid_reason: str = ""
    vertex_count: int = 0
    qa_flags: list[str] = field(default_factory=list)


def parse_geometry(value: dict[str, Any] | str | None) -> GEOSGeometry | None:
    """GeoJSON (dict or string) -> GEOSGeometry in 4326, or None. Raises ValueError on garbage."""
    if value is None:
        return None
    raw = value if isinstance(value, str) else json.dumps(value)
    try:
        geom = GEOSGeometry(raw, srid=4326)
    except Exception as exc:  # GEOS raises several types
        raise ValueError(f"Invalid GeoJSON geometry: {exc}") from exc
    if geom.srid not in (None, 4326):
        geom.transform(4326)
    geom.srid = 4326
    return geom


def check_type(geometry_type: str, geom: GEOSGeometry | None) -> SchemaIssue | None:
    if geometry_type == "none":
        if geom is not None:
            return SchemaIssue("geom", "geometry_type", "This layer has no geometry")
        return None
    if geom is None:
        return SchemaIssue("geom", "required", f"A {geometry_type} geometry is required")
    if geom.geom_type not in ALLOWED_TYPES[geometry_type]:
        return SchemaIssue(
            "geom", "geometry_type", f"Expected {geometry_type}, got {geom.geom_type}"
        )
    return None


def measure(geom: GEOSGeometry | None) -> Measures:
    """All derived values in one PostGIS round trip."""
    if geom is None:
        return Measures()
    with connection.cursor() as cur:
        cur.execute(
            """
            WITH g AS (SELECT ST_GeomFromEWKB(%s) AS geom)
            SELECT
              ST_IsValid(geom), ST_IsValidReason(geom), ST_NPoints(geom),
              CASE WHEN ST_Dimension(geom) = 2 THEN ST_Area(geom::geography) END,
              CASE WHEN ST_Dimension(geom) = 2 THEN ST_Perimeter(geom::geography) END,
              CASE WHEN ST_Dimension(geom) = 1 THEN ST_Length(geom::geography) END,
              CASE WHEN ST_Dimension(geom) = 2 AND ST_IsValid(geom) THEN
                   ST_Contains(geom, ST_Centroid(geom)) END,
              CASE WHEN ST_Dimension(geom) = 2 AND ST_IsValid(geom)
                   THEN ST_AsEWKT(ST_Centroid(geom)) END,
              CASE WHEN ST_Dimension(geom) = 2 AND ST_IsValid(geom)
                   THEN ST_AsEWKT(ST_PointOnSurface(geom)) END
            FROM g
            """,
            [bytes(geom.ewkb)],
        )
        row = cur.fetchone()
    assert row is not None
    is_valid, reason, npoints, area, perimeter, length, contains, centroid_wkt, pos_wkt = row
    m = Measures(
        area_m2=float(area) if area is not None else None,
        perimeter_m=float(perimeter) if perimeter is not None else None,
        length_m=float(length) if length is not None else None,
        is_valid=bool(is_valid),
        valid_reason="" if is_valid else str(reason),
        vertex_count=int(npoints or 0),
    )
    if centroid_wkt is not None:
        if contains:
            m.centroid = GEOSGeometry(str(centroid_wkt))
            m.centroid_method = "centroid"
        else:
            m.centroid = GEOSGeometry(str(pos_wkt))
            m.centroid_method = "point_on_surface"
            m.qa_flags.append("centroid_fallback")
    return m


def validate_against_profile(
    geometry_type: str, geom: GEOSGeometry | None, measures: Measures, profile: dict[str, Any]
) -> tuple[list[SchemaIssue], list[str]]:
    """Rules from the resolved capture profile: (rejections, qa flags)."""
    issues: list[SchemaIssue] = []
    flags: list[str] = []
    if geom is None or geometry_type == "none":
        return issues, flags
    validation = profile.get("validation") or {}
    if not measures.is_valid:
        if validation.get("preventSelfIntersection", True):
            issues.append(
                SchemaIssue("geom", "invalid", f"Geometry is not valid: {measures.valid_reason}")
            )
        else:
            flags.append("invalid_geometry")
    min_vertices = profile.get("minVertices")
    if isinstance(min_vertices, int) and geometry_type in ("line", "polygon"):
        # A closed ring repeats its first point; count distinct vertices.
        distinct = measures.vertex_count - (1 if geometry_type == "polygon" else 0)
        if distinct < min_vertices:
            issues.append(
                SchemaIssue(
                    "geom", "min_vertices", f"At least {min_vertices} vertices are required"
                )
            )
    if geometry_type == "polygon" and measures.area_m2 is not None:
        min_area = validation.get("minAreaSqm")
        max_area = validation.get("maxAreaSqm")
        if isinstance(min_area, int | float) and measures.area_m2 < min_area:
            issues.append(
                SchemaIssue(
                    "geom", "min_area", f"Area {measures.area_m2:.1f} m² is below {min_area} m²"
                )
            )
        if isinstance(max_area, int | float) and measures.area_m2 > max_area:
            issues.append(
                SchemaIssue(
                    "geom", "max_area", f"Area {measures.area_m2:.1f} m² is above {max_area} m²"
                )
            )
    return issues, flags


def extent_flags(
    geom: GEOSGeometry | None, extent: Polygon | None, assigned_area: GEOSGeometry | None
) -> list[str]:
    """Never a rejection: outside the project extent or the collector's area is only flagged."""
    flags: list[str] = []
    if geom is None:
        return flags
    if extent is not None and not extent.intersects(geom):
        flags.append("outside_extent")
    if assigned_area is not None and not assigned_area.intersects(geom):
        flags.append("outside_assigned_area")
    return flags
