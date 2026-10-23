"""Overlap QA: two overlapping farms are flagged (or blocked when the profile says so)."""

from typing import Any

import pytest

from precisecapture.common.tenancy import tenant_context
from precisecapture.features.geometry import parse_geometry
from precisecapture.features.qa import check_overlaps, find_overlaps, overlap_rules
from tests.factories import FeatureFactory, LayerFactory, OrganisationFactory, ProjectFactory

pytestmark = pytest.mark.django_db

LAT, LON = 6.33, -2.83
D = 100 / 110_574  # ~100 m in degrees of latitude; close enough in longitude at 6°N


def square(x: float, y: float, size: float = D) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]],
    }


@pytest.fixture
def layer():
    org = OrganisationFactory()
    with tenant_context(org.id):
        layer = LayerFactory(org=org, project=ProjectFactory(org=org), geometry_type="polygon")
        FeatureFactory(
            org=org, layer=layer, geom=parse_geometry(square(LON, LAT))
        )  # existing farm A
    return layer


PROFILE = {
    "validation": {
        "topology": {"noOverlapWith": ["self"], "onOverlap": "flag", "overlapToleranceSqm": 1}
    }
}


def test_overlapping_farm_is_flagged(layer):
    with tenant_context(layer.org_id):
        overlapping = parse_geometry(square(LON + D / 2, LAT + D / 2))  # half overlaps farm A
        issues, flags, overlaps = check_overlaps(
            layer_id=layer.id,
            org_id=layer.org_id,
            geom=overlapping,
            exclude_feature_id=None,
            profile=PROFILE,
        )
        assert issues == [] and flags == ["overlap"]
        assert len(overlaps) == 1 and abs(overlaps[0].area_m2 - 2_500) / 2_500 < 0.02


def test_touching_and_sliver_overlaps_are_ignored(layer):
    with tenant_context(layer.org_id):
        touching = parse_geometry(square(LON + D, LAT))  # shares an edge only
        assert (
            check_overlaps(
                layer_id=layer.id,
                org_id=layer.org_id,
                geom=touching,
                exclude_feature_id=None,
                profile=PROFILE,
            )[1]
            == []
        )
        sliver = parse_geometry(
            square(LON + D - D / 200, LAT, size=D)
        )  # 0.5 m strip = ~50 m² > 1 m² -> still an overlap
        assert check_overlaps(
            layer_id=layer.id,
            org_id=layer.org_id,
            geom=sliver,
            exclude_feature_id=None,
            profile=PROFILE,
        )[1] == ["overlap"]
        big_tolerance = {
            "validation": {"topology": {"noOverlapWith": ["self"], "overlapToleranceSqm": 100}}
        }
        assert (
            check_overlaps(
                layer_id=layer.id,
                org_id=layer.org_id,
                geom=sliver,
                exclude_feature_id=None,
                profile=big_tolerance,
            )[1]
            == []
        )


def test_block_mode_rejects(layer):
    with tenant_context(layer.org_id):
        profile = {"validation": {"topology": {"noOverlapWith": ["self"], "onOverlap": "block"}}}
        issues, flags, _ = check_overlaps(
            layer_id=layer.id,
            org_id=layer.org_id,
            geom=parse_geometry(square(LON + D / 2, LAT)),
            exclude_feature_id=None,
            profile=profile,
        )
        assert [i.code for i in issues] == ["overlap"] and flags == []


def test_disabled_rule_and_self_exclusion(layer):
    with tenant_context(layer.org_id):
        existing = layer.features.first()
        assert existing is not None and existing.geom is not None
        assert (
            check_overlaps(
                layer_id=layer.id,
                org_id=layer.org_id,
                geom=existing.geom,
                exclude_feature_id=None,
                profile={},
            )[1]
            == []
        )
        # editing farm A itself must not report an overlap with farm A
        assert existing.geom is not None
        assert (
            find_overlaps(
                layer_id=layer.id,
                org_id=layer.org_id,
                geom=existing.geom,
                exclude_feature_id=existing.id,
                tolerance_sqm=1,
            )
            == []
        )
        assert overlap_rules({}) == (False, "flag", 1.0)


def test_deleted_and_other_layer_features_do_not_count(layer):
    with tenant_context(layer.org_id):
        other_layer = LayerFactory(
            org=layer.org, project=layer.project, geometry_type="polygon", key="lyr_other"
        )
        FeatureFactory(org=layer.org, layer=other_layer, geom=parse_geometry(square(LON, LAT)))
        layer.features.update(deleted=True)
        probe = parse_geometry(square(LON, LAT))
        assert probe is not None
        assert (
            find_overlaps(
                layer_id=layer.id,
                org_id=layer.org_id,
                geom=probe,
                exclude_feature_id=None,
                tolerance_sqm=1,
            )
            == []
        )
