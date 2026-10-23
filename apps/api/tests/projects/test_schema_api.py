"""Schema draft/publish/versions, capture profiles, templates and the bundle."""

from typing import Any

import pytest

from precisecapture.common.tenancy import tenant_context
from precisecapture.projects.models import LayerSchemaVersion
from tests.projects.conftest import example

pytestmark = pytest.mark.django_db


@pytest.fixture
def layers(people, project):
    api = people["manager"]["api"]
    farmers = api.post(
        f"/api/v1/projects/{project.id}/layers",
        {"name": "Farmers", "key": "lyr_farmers", "geometry_type": "none"},
    ).json()
    farms = api.post(
        f"/api/v1/projects/{project.id}/layers",
        {
            "name": "Farms",
            "key": "lyr_farms",
            "geometry_type": "polygon",
            "capture_profile": example("farms.capture-profile.json"),
        },
    ).json()
    return farmers, farms


def publish(api: Any, layer_id: str, attributes: dict[str, Any]) -> Any:
    r = api.put(f"/api/v1/layers/{layer_id}/schema", {"attributes": attributes})
    assert r.status_code == 200, r.content
    return api.post(f"/api/v1/layers/{layer_id}/schema/publish")


# --- publish -----------------------------------------------------------------------------


def test_publish_pilot_schemas(people, project, layers):
    api = people["manager"]["api"]
    farmers, farms = layers
    r = publish(api, farmers["id"], example("farmers.layer-schema.json"))
    assert r.status_code == 200, r.content
    assert r.json() == {"version": 1, "config_version": r.json()["config_version"], "warnings": []}
    r = publish(api, farms["id"], example("farms.layer-schema.json"))
    assert r.status_code == 200, r.content
    s = api.get(f"/api/v1/layers/{farms['id']}/schema").json()
    assert (
        s["current_version"] == 1
        and s["draft"] is None
        and s["current"]["layerId"] == "lyr_farms"
        and s["current"]["version"] == 1
    )
    assert (
        api.get(f"/api/v1/layers/{farms['id']}/schema/versions/1").json()["attributes"]["fields"][
            0
        ]["key"]
        == "farmer"
    )
    assert api.get(f"/api/v1/layers/{farms['id']}/schema/versions/9").status_code == 404
    # collectors may read schemas (the phone needs them) but not write
    assert (
        people["collector"]["api"]
        .put(f"/api/v1/layers/{farms['id']}/schema", {"attributes": {}})
        .status_code
        == 403
    )


def test_publish_invalid_schema_is_422_with_per_field_errors(people, layers):
    api = people["manager"]["api"]
    _, farms = layers
    bad: dict[str, Any] = {
        "fields": [
            {"key": "crop", "type": "select_one", "options": "list:crops"},  # list missing
            {"key": "Crop Name", "type": "text"},  # bad key -> schema error
        ]
    }
    r = publish(api, farms["id"], bad)
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} == {
        "fields.1.key"
    }  # structural errors come first
    bad["fields"][1]["key"] = "crop"  # duplicate key
    bad["fields"].append({"key": "farmer", "type": "relation", "relation": {"layer": "lyr_nope"}})
    bad["fields"].append(
        {
            "key": "note",
            "type": "text",
            "relevant": "${missing} = 1",
            "constraint": "string-length(. > 1",
        }
    )
    bad["fields"].append({"key": "area", "type": "calculate", "expression": "nearest('x', 'y')"})
    r = publish(api, farms["id"], bad)
    assert r.status_code == 422
    errors = {(e["field"], e["code"]) for e in r.json()["errors"]}
    assert errors == {
        ("fields.0.options", "unknown_list"),
        ("fields.1.key", "duplicate"),
        ("fields.2.relation.layer", "unknown_layer"),
        ("fields.3.relevant", "expression"),
        ("fields.3.constraint", "expression"),
        ("fields.4.expression", "expression"),
    }
    assert LayerSchemaVersion.all_tenants.count() == 0


def test_type_change_rejected_unless_safe_widening(people, layers):
    api = people["manager"]["api"]
    _, farms = layers
    v1 = {
        "fields": [
            {"key": "year", "type": "integer"},
            {"key": "crop", "type": "select_one", "options": [{"value": "a", "label": "A"}]},
            {"key": "code", "type": "phone"},
        ]
    }
    assert publish(api, farms["id"], v1).status_code == 200
    breaking = {
        "fields": [
            {"key": "year", "type": "text"},
            {"key": "crop", "type": "text"},
            {"key": "code", "type": "integer"},
        ]
    }
    r = publish(api, farms["id"], breaking)
    assert r.status_code == 422
    assert {e["field"] for e in r.json()["errors"]} == {
        "fields[year].type",
        "fields[crop].type",
        "fields[code].type",
    }
    assert all(e["code"] == "incompatible_type" for e in r.json()["errors"])
    widened = {
        "fields": [
            {"key": "year", "type": "decimal"},
            {"key": "crop", "type": "select_many", "options": [{"value": "a", "label": "A"}]},
            {"key": "code", "type": "text"},
            {"key": "consent", "type": "yes_no", "required": True},
        ]
    }
    r = publish(api, farms["id"], widened)
    assert r.status_code == 200, r.content
    assert r.json()["version"] == 2
    assert r.json()["warnings"] == ["New required attributes apply to new captures only: consent"]
    # removing a field warns but is allowed
    r = publish(api, farms["id"], {"fields": [{"key": "year", "type": "decimal"}]})
    assert r.status_code == 200 and "Removed attributes stay in old data" in r.json()["warnings"][0]
    assert [
        v["version"] for v in api.get(f"/api/v1/layers/{farms['id']}/schema/versions").json()
    ] == [1, 2, 3]


def test_publish_without_draft_or_identical_draft_is_409(people, layers):
    api = people["manager"]["api"]
    farmers, _ = layers
    assert api.post(f"/api/v1/layers/{farmers['id']}/schema/publish").status_code == 409
    doc = {"fields": [{"key": "name", "type": "text"}]}
    assert publish(api, farmers["id"], doc).status_code == 200
    assert publish(api, farmers["id"], doc).status_code == 409


def test_validate_endpoint_is_a_dry_run(people, layers):
    api = people["manager"]["api"]
    farmers, _ = layers
    r = api.post(
        f"/api/v1/layers/{farmers['id']}/schema/validate",
        {"attributes": {"fields": [{"key": "x", "type": "nope"}]}},
    )
    assert r.status_code == 200 and r.json()["errors"][0]["field"] == "fields.0.type"
    assert api.get(f"/api/v1/layers/{farmers['id']}/schema").json()["current_version"] == 0


# --- capture profile ---------------------------------------------------------------------


def test_capture_profile_resolves_org_project_layer(people, project, layers, org):
    api = people["manager"]["api"]
    _, farms = layers
    r = api.get(f"/api/v1/layers/{farms['id']}/capture-profile")
    assert r.status_code == 200
    resolved = r.json()["resolved"]
    assert resolved["gps"]["maxAccuracyMeters"] == 5  # layer wins over org (8)
    assert resolved["stream"]["intervalMeters"] == 3  # layer profile and project agree
    r = api.put(
        f"/api/v1/layers/{farms['id']}/capture-profile",
        {"capture_profile": {"stream": {"intervalMeters": 1, "allowedIntervalsMeters": [1, 2, 3]}}},
    )
    assert r.status_code == 200, r.content
    assert r.json()["resolved"]["stream"]["intervalMeters"] == 1
    assert r.json()["resolved"]["gps"]["maxAccuracyMeters"] == 8  # back to the org default
    assert r.json()["config_version"] == project.config_version + 3  # 2 layer creates + this


def test_capture_profile_validation_errors(people, layers):
    api = people["manager"]["api"]
    _, farms = layers
    r = api.put(
        f"/api/v1/layers/{farms['id']}/capture-profile",
        {"capture_profile": {"stream": {"intervalMeters": 0.5}, "bogus": 1}},
    )
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} == {
        "stream.intervalMeters",
        "bogus",
    }
    r = api.put(
        f"/api/v1/layers/{farms['id']}/capture-profile",
        {
            "capture_profile": {
                "modes": {"allowed": ["tap"], "default": "stream"},
                "snapping": {"layers": ["self", "lyr_roads"]},
            }
        },
    )
    assert r.status_code == 422
    assert {(e["field"], e["code"]) for e in r.json()["errors"]} == {
        ("modes.default", "not_allowed"),
        ("snapping.layers.1", "unknown_layer"),
    }


# --- templates -----------------------------------------------------------------------------


def test_save_as_template_and_create_from_template(people, project, layers, org):
    api = people["manager"]["api"]
    _, farms = layers
    assert (
        api.post(
            f"/api/v1/layers/{farms['id']}/save-as-template", {"name": "Farm plot"}
        ).status_code
        == 409
    )  # nothing published
    assert publish(api, farms["id"], example("farms.layer-schema.json")).status_code == 200
    r = api.post(
        f"/api/v1/layers/{farms['id']}/save-as-template",
        {"name": "Farm plot", "description": "EUDR plot"},
    )
    assert r.status_code == 201, r.content
    template = r.json()
    assert template["geometry_type"] == "polygon" and "version" not in template["attributes"]
    assert (
        api.post(
            f"/api/v1/layers/{farms['id']}/save-as-template", {"name": "Farm plot"}
        ).status_code
        == 409
    )
    assert [t["name"] for t in api.get("/api/v1/layer-templates").json()] == ["Farm plot"]

    r = api.post(
        f"/api/v1/projects/{project.id}/layers/from-template",
        {"template_id": template["id"], "name": "Farms 2", "key": "lyr_farms2"},
    )
    assert r.status_code == 201, r.content
    new = r.json()
    assert new["has_draft"] and new["capture_profile"]["stream"]["intervalMeters"] == 3
    # the draft publishes as-is (relation target lyr_farmers exists in this project)
    assert api.post(f"/api/v1/layers/{new['id']}/schema/publish").status_code == 200
    assert api.delete(f"/api/v1/layer-templates/{template['id']}").status_code == 204
    assert api.get("/api/v1/layer-templates").json() == []


# --- bundle ----------------------------------------------------------------------------------


def test_bundle_contents_etag_and_304(people, project, layers, org):
    api = people["manager"]["api"]
    farmers, farms = layers
    publish(api, farmers["id"], example("farmers.layer-schema.json"))
    publish(api, farms["id"], example("farms.layer-schema.json"))
    r = api.get(f"/api/v1/projects/{project.id}/bundle")
    assert r.status_code == 200, r.content
    assert r["X-Server-Seq"] == "0" and r["ETag"].startswith('"')
    body = r.json()
    assert body["project"]["id"] == str(project.id) and body["my_role"] == "manager"
    assert [layer["key"] for layer in body["layers"]] == ["lyr_farmers", "lyr_farms"]
    farms_b = body["layers"][1]
    assert farms_b["id"] == farms["id"] and farms_b["schema_version"] == 1
    assert farms_b["schema"]["fields"][0]["key"] == "farmer"
    assert set(farms_b["lists"]) == {"crop", "ownership"}
    assert (
        farms_b["capture_profile"]["gps"]["maxAccuracyMeters"] == 5
        and farms_b["capture_profile"]["autoClose"]["locked"] is True
    )
    assert (
        body["basemap_packs"] == [] and body["config_version"] == 5
    )  # 2 creates + 2 publishes + 1
    etag = r["ETag"]
    assert (
        api.get(f"/api/v1/projects/{project.id}/bundle", HTTP_IF_NONE_MATCH=etag).status_code == 304
    )
    # a config change yields a new ETag
    api.put(
        f"/api/v1/layers/{farms['id']}/capture-profile",
        {"capture_profile": {"stream": {"intervalMeters": 2}}},
    )
    r = api.get(f"/api/v1/projects/{project.id}/bundle", HTTP_IF_NONE_MATCH=etag)
    assert r.status_code == 200 and r["ETag"] != etag


def test_bundle_is_per_user_and_changes_with_role_or_area(people, project, layers):
    api_m, api_c = people["manager"]["api"], people["collector"]["api"]
    collector = people["collector"]["user"]
    assert api_c.get(f"/api/v1/projects/{project.id}/bundle").status_code == 403
    api_m.post(
        f"/api/v1/projects/{project.id}/members",
        {"user_id": str(collector.id), "role": "collector"},
    )
    r1 = api_c.get(f"/api/v1/projects/{project.id}/bundle")
    assert r1.status_code == 200 and r1.json()["my_role"] == "collector"
    assert r1["ETag"] != api_m.get(f"/api/v1/projects/{project.id}/bundle")["ETag"]
    api_m.patch(f"/api/v1/projects/{project.id}/members/{collector.id}", {"role": "viewer"})
    r2 = api_c.get(f"/api/v1/projects/{project.id}/bundle", HTTP_IF_NONE_MATCH=r1["ETag"])
    assert r2.status_code == 200 and r2["ETag"] != r1["ETag"] and r2.json()["my_role"] == "viewer"
    square = {
        "type": "Polygon",
        "coordinates": [[[-2.6, 6.1], [-2.4, 6.1], [-2.4, 6.3], [-2.6, 6.3], [-2.6, 6.1]]],
    }
    api_m.patch(f"/api/v1/projects/{project.id}/members/{collector.id}", {"assigned_area": square})
    r3 = api_c.get(f"/api/v1/projects/{project.id}/bundle", HTTP_IF_NONE_MATCH=r2["ETag"])
    assert r3.status_code == 200 and r3["ETag"] != r2["ETag"]
    api_m.delete(f"/api/v1/projects/{project.id}/members/{collector.id}")
    assert api_c.get(f"/api/v1/projects/{project.id}/bundle").status_code == 403


def test_bundle_cross_org_is_404(people, project):
    from tests.factories import OrganisationFactory, ProjectFactory

    other = OrganisationFactory()
    with tenant_context(other.id):
        foreign = ProjectFactory(org=other)
    assert people["admin"]["api"].get(f"/api/v1/projects/{foreign.id}/bundle").status_code == 404
