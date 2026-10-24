"""Capture profile resolution and semantics, driven by the shared vectors."""

import copy
from typing import Any

import pytest

from precisecapture.common.capture_profile import (
    resolve_capture_profile,
    validate_capture_profile_semantics,
)
from precisecapture.common.schema_validation import load_test_vectors

RESOLUTION = load_test_vectors("capture-profile-resolution.json")["cases"]
SEMANTICS = load_test_vectors("capture-profile-semantics.json")["cases"]


@pytest.mark.parametrize("case", RESOLUTION, ids=[c["name"] for c in RESOLUTION])
def test_resolution_vector(case):
    result = resolve_capture_profile(case["org"], case["project"], case["layer"], case["collector"])
    assert result == case["expect"]


@pytest.mark.parametrize("case", SEMANTICS, ids=[c["name"] for c in SEMANTICS])
def test_semantics_vector(case):
    issues = validate_capture_profile_semantics(
        case["profile"],
        geometry_type=case.get("geometryType"),
        layer_keys=case.get("layerKeys"),
        reference_layer_keys=case.get("referenceLayerKeys"),
    )
    assert {(i.field, i.code) for i in issues} == {
        (e["field"], e["code"]) for e in case["expectErrors"]
    }
    assert len(issues) == len(case["expectErrors"])
    assert all(i.message for i in issues)


def test_resolution_does_not_mutate_inputs():
    org: dict[str, Any] = {
        "gps": {"maxAccuracyMeters": 5, "averaging": {"enabled": True, "locked": True}}
    }
    layer: dict[str, Any] = {
        "gps": {"averaging": {"enabled": False}},
        "stream": {"intervalMeters": 3},
    }
    collector: dict[str, Any] = {"stream": {"intervalMeters": 1}}
    snapshot = copy.deepcopy((org, layer, collector))
    result = resolve_capture_profile(org, None, layer, collector)
    assert (org, layer, collector) == snapshot
    result["stream"]["intervalMeters"] = 99
    assert layer["stream"]["intervalMeters"] == 3
