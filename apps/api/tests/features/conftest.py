from typing import Any

import pytest

from tests.projects.conftest import Api, example, org, people, project

__all__ = ["Api", "org", "people", "project"]  # re-exported fixtures


@pytest.fixture
def pilot(people, project):
    """Farmers (none) and Farms (polygon) layers published from the examples."""
    api = people["manager"]["api"]
    out: dict[str, Any] = {}
    for name, key, gtype, schema, profile in (
        ("Farmers", "lyr_farmers", "none", "farmers.layer-schema.json", {}),
        (
            "Farms",
            "lyr_farms",
            "polygon",
            "farms.layer-schema.json",
            example("farms.capture-profile.json"),
        ),
    ):
        layer = api.post(
            f"/api/v1/projects/{project.id}/layers",
            {"name": name, "key": key, "geometry_type": gtype, "capture_profile": profile},
        ).json()
        assert (
            api.put(
                f"/api/v1/layers/{layer['id']}/schema", {"attributes": example(schema)}
            ).status_code
            == 200
        )
        r = api.post(f"/api/v1/layers/{layer['id']}/schema/publish")
        assert r.status_code == 200, r.content
        out[key] = layer
    return out
