"""Geometry measures and profile rules (ENGINEERING_NOTES.md §3 acceptance criteria)."""

from typing import Any

import pytest
from django.contrib.gis.geos import GEOSGeometry, Point, Polygon

from precisecapture.features.geometry import (
    check_type,
    extent_flags,
    measure,
    parse_geometry,
    validate_against_profile,
)

pytestmark = pytest.mark.django_db

# A 100 m x 100 m square near Juaboso, Ghana (6.33N, -2.83E), built in metres then unprojected.
# 1 ha = 10 000 m². Degrees per metre at lat 6.33: lon 1/(111320*cos(6.33°)), lat 1/110574.
LAT, LON = 6.33, -2.83
DLAT = 100 / 110_574
DLON = 100 / (111_320 * 0.99390)  # cos(6.33°) ≈ 0.99390
SQUARE = {
    "type": "Polygon",
    "coordinates": [
        [[LON, LAT], [LON + DLON, LAT], [LON + DLON, LAT + DLAT], [LON, LAT + DLAT], [LON, LAT]]
    ],
}
# An L shape whose centroid falls outside the polygon: two 100 m arms of a 300 m square.
L_SHAPE = {
    "type": "Polygon",
    "coordinates": [
        [
            [LON, LAT],
            [LON + 3 * DLON, LAT],
            [LON + 3 * DLON, LAT + DLAT],
            [LON + DLON, LAT + DLAT],
            [LON + DLON, LAT + 3 * DLAT],
            [LON, LAT + 3 * DLAT],
            [LON, LAT],
        ]
    ],
}
BOWTIE = {
    "type": "Polygon",
    "coordinates": [
        [[LON, LAT], [LON + DLON, LAT + DLAT], [LON + DLON, LAT], [LON, LAT + DLAT], [LON, LAT]]
    ],
}


def test_known_square_in_ghana_is_one_hectare_within_0_1_percent():
    m = measure(parse_geometry(SQUARE))
    assert m.area_m2 is not None and abs(m.area_m2 - 10_000) / 10_000 < 0.001
    assert m.perimeter_m is not None and abs(m.perimeter_m - 400) / 400 < 0.001
    assert m.centroid_method == "centroid" and m.qa_flags == []
    assert isinstance(m.centroid, Point) and abs(m.centroid.x - (LON + DLON / 2)) < 1e-6


def test_l_shape_falls_back_to_point_on_surface_with_a_flag():
    geom = parse_geometry(L_SHAPE)
    m = measure(geom)
    assert m.centroid_method == "point_on_surface" and "centroid_fallback" in m.qa_flags
    assert geom is not None and m.centroid is not None and geom.contains(m.centroid)
    assert m.area_m2 is not None and abs(m.area_m2 - 50_000) / 50_000 < 0.001


def test_line_length_and_no_area():
    line = parse_geometry({"type": "LineString", "coordinates": [[LON, LAT], [LON + DLON, LAT]]})
    m = measure(line)
    assert m.length_m is not None and abs(m.length_m - 100) / 100 < 0.001
    assert m.area_m2 is None and m.centroid is None


def test_self_intersection_rejected_when_profile_says_so():
    m = measure(parse_geometry(BOWTIE))
    assert not m.is_valid and "Self-intersection" in m.valid_reason
    issues, flags = validate_against_profile(
        "polygon", parse_geometry(BOWTIE), m, {"validation": {"preventSelfIntersection": True}}
    )
    assert [i.code for i in issues] == ["invalid"] and flags == []
    issues, flags = validate_against_profile(
        "polygon", parse_geometry(BOWTIE), m, {"validation": {"preventSelfIntersection": False}}
    )
    assert issues == [] and flags == ["invalid_geometry"]


def test_min_vertices_and_area_bounds():
    geom = parse_geometry(SQUARE)
    m = measure(geom)
    issues, _ = validate_against_profile(
        "polygon",
        geom,
        m,
        {"minVertices": 5, "validation": {"minAreaSqm": 20_000, "maxAreaSqm": 5_000}},
    )
    assert sorted(i.code for i in issues) == ["max_area", "min_area", "min_vertices"]
    issues, _ = validate_against_profile(
        "polygon",
        geom,
        m,
        {"minVertices": 4, "validation": {"minAreaSqm": 100, "maxAreaSqm": 2_000_000}},
    )
    assert issues == []


def _code(issue: Any) -> str:
    assert issue is not None
    return str(issue.code)


def test_type_checks():
    assert check_type("none", None) is None
    assert _code(check_type("none", parse_geometry(SQUARE))) == "geometry_type"
    assert _code(check_type("polygon", None)) == "required"
    assert _code(check_type("point", parse_geometry(SQUARE))) == "geometry_type"
    assert check_type("polygon", parse_geometry(SQUARE)) is None


def test_parse_geometry_errors_and_reprojection():
    with pytest.raises(ValueError):
        parse_geometry({"type": "Polygon", "coordinates": "nope"})
    assert parse_geometry(None) is None
    g = parse_geometry({"type": "Point", "coordinates": [LON, LAT]})
    assert g is not None and g.srid == 4326


def test_extent_flags():
    geom = parse_geometry(SQUARE)
    far = Polygon.from_bbox((0, 0, 1, 1))
    near = Polygon.from_bbox((-3, 6, -2, 7))
    _ = GEOSGeometry
    assert extent_flags(geom, far, None) == ["outside_extent"]
    assert extent_flags(geom, near, far) == ["outside_assigned_area"]
    assert extent_flags(geom, near, near) == []
    assert extent_flags(None, far, far) == []
