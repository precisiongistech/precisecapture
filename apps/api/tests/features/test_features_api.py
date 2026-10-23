"""Feature write path, history, review, list/detail, idempotency, tiles (M5 acceptance criteria)."""

import uuid
from typing import Any
from unittest import mock

import pytest

from precisecapture.common.ids import uuid7
from precisecapture.common.tenancy import tenant_context
from precisecapture.features.models import Feature, FeatureHistory, FeatureRelation
from tests.projects.conftest import Api

pytestmark = pytest.mark.django_db

LAT, LON = 6.33, -2.83
D = 100 / 110_574


def square(x: float = LON, y: float = LAT, size: float = D) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]],
    }


FARMER = {
    "full_name": "Ama Mensah",
    "gender": "female",
    "id_type": "ghana_card",
    "id_number": "GHA-123456789-0",
    "region": "western_north",
    "district": "juaboso",
    "community": "Juaboso",
    "consent": "yes",
}


def create_farmer(api: Api, layers: dict[str, Any], **over: Any) -> Any:
    return api.post(
        f"/api/v1/layers/{layers['lyr_farmers']['id']}/features", {"attributes": {**FARMER, **over}}
    )


def farm_attrs(farmer_id: str, **over: Any) -> dict[str, Any]:
    photo = str(uuid.uuid4())
    return {"farmer": farmer_id, "crop": "cocoa", "planting_year": 2018, "photos": [photo], **over}


def create_farm(
    api: Api,
    layers: dict[str, Any],
    farmer_id: str,
    geom: dict[str, Any] | None = None,
    **over: Any,
) -> Any:
    return api.post(
        f"/api/v1/layers/{layers['lyr_farms']['id']}/features",
        {"id": str(uuid7()), "geom": geom or square(), "attributes": farm_attrs(farmer_id, **over)},
    )


# --- create --------------------------------------------------------------------------------


def test_create_farmer_and_farm_with_computed_fields_and_history(people, pilot):
    api = people["collector"]["api"]
    assert (
        api.post(f"/api/v1/layers/{pilot['lyr_farms']['id']}/features", {}).status_code == 403
    )  # not a project member
    people["manager"]["api"].post(
        f"/api/v1/projects/{pilot['lyr_farms']['project_id']}/members",
        {"user_id": str(people["collector"]["user"].id)},
    )
    r = create_farmer(api, pilot)
    assert r.status_code == 201, r.content
    farmer = r.json()
    assert farmer["geom"] is None and farmer["version"] == 1 and farmer["status"] == "submitted"
    r = create_farm(api, pilot, farmer["id"])
    assert r.status_code == 201, r.content
    farm = r.json()
    assert (
        abs(farm["computed"]["area_ha"] - 1.0) < 0.002
        and farm["computed"]["centroid_method"] == "centroid"
    )
    assert farm["attributes"]["area_ha"] == pytest.approx(
        1.0, rel=0.002
    )  # calculate recomputed by the server
    assert farm["attributes"]["needs_polygon_for_eudr"] == "no"
    assert farm["qa_flags"] == []
    with tenant_context(
        pilot["lyr_farms"]["org_id"]
        if "org_id" in pilot["lyr_farms"]
        else people["collector"]["user"].memberships.first().org_id
    ):
        assert FeatureRelation.objects.get(from_feature_id=farm["id"]).to_feature_id == uuid.UUID(
            farmer["id"]
        )
        assert FeatureHistory.objects.filter(feature_id=farm["id"]).count() == 1
    detail = api.get(f"/api/v1/features/{farm['id']}").json()
    assert detail["relations"] == {"farmer": farmer["id"]}


def test_create_validation_errors_are_per_field(people, pilot):
    api = people["manager"]["api"]
    r = create_farm(api, pilot, str(uuid.uuid4()), crop="bananas", planting_year=1800)
    assert r.status_code == 422
    errors = {e["field"]: e["code"] for e in r.json()["errors"]}
    assert errors == {"farmer": "unknown_relation", "crop": "option", "planting_year": "min"}
    # missing photos (min 1) and a bow-tie polygon
    farmer = create_farmer(api, pilot).json()
    bowtie = {
        "type": "Polygon",
        "coordinates": [
            [[LON, LAT], [LON + D, LAT + D], [LON + D, LAT], [LON, LAT + D], [LON, LAT]]
        ],
    }
    r = api.post(
        f"/api/v1/layers/{pilot['lyr_farms']['id']}/features",
        {"geom": bowtie, "attributes": {"farmer": farmer["id"], "crop": "cocoa", "photos": []}},
    )
    assert r.status_code == 422
    assert {(e["field"], e["code"]) for e in r.json()["errors"]} >= {
        ("geom", "invalid"),
        ("photos", "min_count"),
    }
    with tenant_context(people["manager"]["user"].memberships.first().org_id):
        assert (
            Feature.objects.filter(layer_id=pilot["lyr_farms"]["id"]).count() == 0
        )  # nothing written


def test_geometry_type_and_unique_and_table_layer(people, pilot):
    api = people["manager"]["api"]
    r = api.post(
        f"/api/v1/layers/{pilot['lyr_farmers']['id']}/features",
        {"geom": square(), "attributes": FARMER},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "geometry_type"
    assert create_farmer(api, pilot).status_code == 201
    r = create_farmer(api, pilot)  # same id_number -> unique
    assert r.status_code == 422 and {e["code"] for e in r.json()["errors"]} == {"unique"}
    farmer = create_farmer(api, pilot, id_number="GHA-000000000-1").json()
    r = api.post(
        f"/api/v1/layers/{pilot['lyr_farms']['id']}/features",
        {
            "geom": {"type": "Point", "coordinates": [LON, LAT]},
            "attributes": farm_attrs(farmer["id"]),
        },
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "geometry_type"


def test_overlapping_farms_are_flagged_and_l_shape_falls_back(people, pilot):
    api = people["manager"]["api"]
    farmer = create_farmer(api, pilot).json()
    assert create_farm(api, pilot, farmer["id"]).status_code == 201
    r = create_farm(api, pilot, farmer["id"], geom=square(LON + D / 2, LAT))
    assert r.status_code == 201 and r.json()["qa_flags"] == ["overlap"]
    l_shape = {
        "type": "Polygon",
        "coordinates": [
            [
                [LON + 5 * D, LAT],
                [LON + 8 * D, LAT],
                [LON + 8 * D, LAT + D],
                [LON + 6 * D, LAT + D],
                [LON + 6 * D, LAT + 3 * D],
                [LON + 5 * D, LAT + 3 * D],
                [LON + 5 * D, LAT],
            ]
        ],
    }
    r = create_farm(api, pilot, farmer["id"], geom=l_shape)
    assert (
        r.status_code == 201
        and r.json()["computed"]["centroid_method"] == "point_on_surface"
        and "centroid_fallback" in r.json()["qa_flags"]
    )


def test_client_id_kept_and_duplicate_rejected(people, pilot):
    api = people["manager"]["api"]
    farmer = create_farmer(api, pilot).json()
    fid = str(uuid.uuid4())
    r = api.post(
        f"/api/v1/layers/{pilot['lyr_farms']['id']}/features",
        {"id": fid, "geom": square(), "attributes": farm_attrs(farmer["id"])},
    )
    assert r.status_code == 201 and r.json()["id"] == fid
    r = api.post(
        f"/api/v1/layers/{pilot['lyr_farms']['id']}/features",
        {"id": fid, "geom": square(), "attributes": farm_attrs(farmer["id"])},
    )
    assert r.status_code == 409


# --- update / delete / restore / review ------------------------------------------------------


def test_patch_versions_history_and_stale_edit(people, pilot):
    api = people["manager"]["api"]
    farmer = create_farmer(api, pilot).json()
    farm = create_farm(api, pilot, farmer["id"]).json()
    r = api.patch(
        f"/api/v1/features/{farm['id']}",
        {"attributes": {**farm["attributes"], "crop": "coffee"}, "base_version": 1},
    )
    assert r.status_code == 200, r.content
    assert r.json()["version"] == 2 and r.json()["attributes"]["crop"] == "coffee"
    r = api.patch(f"/api/v1/features/{farm['id']}", {"status": "draft", "base_version": 1})  # stale
    assert r.status_code == 409 and r.json()["type"].endswith("/stale-version")
    r = api.client.patch(
        f"/api/v1/features/{farm['id']}",
        data='{"geom": null}',
        content_type="application/json",
        HTTP_IF_MATCH='"2"',
        **api._h(),
    )
    assert r.status_code == 422  # polygon layer needs geometry
    r = api.client.patch(
        f"/api/v1/features/{farm['id']}",
        data='{"status": "draft"}',
        content_type="application/json",
        HTTP_IF_MATCH='"2"',
        **api._h(),
    )
    assert r.status_code == 200 and r.json()["version"] == 3
    history = api.get(f"/api/v1/features/{farm['id']}/history").json()
    assert [(h["version"], h["change_type"], h["changed_fields"]) for h in history] == [
        (1, "create", history[0]["changed_fields"]),
        (2, "update", ["crop"]),
        (3, "update", ["status"]),
    ]
    assert "farmer" in history[0]["changed_fields"] and "geom" in history[0]["changed_fields"]


def test_delete_restore_and_review(people, pilot):
    api = people["manager"]["api"]
    farmer = create_farmer(api, pilot).json()
    farm = create_farm(api, pilot, farmer["id"]).json()
    assert api.delete(f"/api/v1/features/{farm['id']}").status_code == 204
    assert api.get(f"/api/v1/features/{farm['id']}").json()["deleted"] is True
    assert (
        api.post(f"/api/v1/features/{farm['id']}/review", {"action": "approve"}).status_code == 409
    )
    r = api.post(f"/api/v1/features/{farm['id']}/restore")
    assert r.status_code == 200 and r.json()["deleted"] is False and r.json()["version"] == 3
    assert (
        api.post(f"/api/v1/features/{farm['id']}/review", {"action": "send_back"}).status_code
        == 422
    )  # note required
    r = api.post(
        f"/api/v1/features/{farm['id']}/review",
        {"action": "send_back", "note": "Boundary missing the north corner"},
    )
    assert (
        r.status_code == 200
        and r.json()["status"] == "sent_back"
        and r.json()["review_note"].startswith("Boundary")
    )
    r = api.post(f"/api/v1/features/{farm['id']}/review", {"action": "approve"})
    assert (
        r.status_code == 200 and r.json()["status"] == "approved" and r.json()["review_note"] == ""
    )
    types = [h["change_type"] for h in api.get(f"/api/v1/features/{farm['id']}/history").json()]
    assert types == ["create", "delete", "restore", "review", "review"]
    # collectors cannot review or restore
    people["manager"]["api"].post(
        f"/api/v1/projects/{pilot['lyr_farms']['project_id']}/members",
        {"user_id": str(people["collector"]["user"].id)},
    )
    assert (
        people["collector"]["api"]
        .post(f"/api/v1/features/{farm['id']}/review", {"action": "approve"})
        .status_code
        == 403
    )


# --- list / detail -----------------------------------------------------------------------------


def test_list_geojson_filters_and_cursor(people, pilot):
    api = people["manager"]["api"]
    farmer = create_farmer(api, pilot).json()
    ids = [
        create_farm(
            api,
            pilot,
            farmer["id"],
            geom=square(LON + i * 2 * D, LAT),
            crop="cocoa" if i % 2 == 0 else "coffee",
        ).json()["id"]
        for i in range(5)
    ]
    api.delete(f"/api/v1/features/{ids[4]}")
    api.post(f"/api/v1/features/{ids[0]}/review", {"action": "approve"})
    base = f"/api/v1/layers/{pilot['lyr_farms']['id']}/features"
    r = api.get(base)
    assert r.status_code == 200 and r["Content-Type"].startswith("application/geo+json")
    body = r.json()
    assert body["type"] == "FeatureCollection" and [f["id"] for f in body["features"]] == ids[:4]
    assert body["features"][0]["properties"]["computed"]["area_ha"] == pytest.approx(1.0, rel=0.002)
    assert [f["id"] for f in api.get(base + "?include_deleted=true").json()["features"]] == ids
    assert [f["id"] for f in api.get(base + "?status=approved").json()["features"]] == [ids[0]]
    assert [f["id"] for f in api.get(base + "?attr.crop=coffee").json()["features"]] == [
        ids[1],
        ids[3],
    ]
    bbox = f"{LON - D},{LAT - D},{LON + D},{LAT + 2 * D}"
    assert [f["id"] for f in api.get(base + f"?bbox={bbox}").json()["features"]] == [ids[0]]
    assert api.get(base + "?bbox=1,2,3").status_code == 422
    page1 = api.get(base + "?limit=3").json()
    assert len(page1["features"]) == 3 and page1["has_more"] and page1["next_cursor"]
    page2 = api.get(base + f"?limit=3&cursor={page1['next_cursor']}").json()
    assert [f["id"] for f in page2["features"]] == [ids[3]] and not page2["has_more"]
    assert api.get(base + "?qa_flag=overlap").json()["features"] == []


def test_features_are_invisible_across_orgs_and_to_non_members(people, pilot):
    api = people["manager"]["api"]
    farmer = create_farmer(api, pilot).json()
    assert people["collector"]["api"].get(f"/api/v1/features/{farmer['id']}").status_code == 403
    assert (
        people["collector"]["api"]
        .get(f"/api/v1/layers/{pilot['lyr_farmers']['id']}/features")
        .status_code
        == 403
    )
    from tests.factories import MembershipFactory, OrganisationFactory, UserFactory
    from tests.projects.conftest import login

    other = OrganisationFactory()
    outsider = UserFactory(email="out@example.org")
    MembershipFactory(user=outsider, org=other, role="owner")
    out_api = Api(api.client, login(api.client, "out@example.org"), str(other.id))
    assert out_api.get(f"/api/v1/features/{farmer['id']}").status_code == 404


# --- idempotency ---------------------------------------------------------------------------------


def test_idempotency_key_replays_the_first_response(people, pilot):
    api = people["manager"]["api"]
    farmer = create_farmer(api, pilot).json()
    body = {"geom": square(), "attributes": farm_attrs(farmer["id"])}
    import json

    headers = {**api._h(), "HTTP_IDEMPOTENCY_KEY": "key-123"}
    r1 = api.client.post(
        f"/api/v1/layers/{pilot['lyr_farms']['id']}/features",
        data=json.dumps(body),
        content_type="application/json",
        **headers,
    )
    r2 = api.client.post(
        f"/api/v1/layers/{pilot['lyr_farms']['id']}/features",
        data=json.dumps(body),
        content_type="application/json",
        **headers,
    )
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"] and r2["Idempotent-Replayed"] == "true"
    with tenant_context(people["manager"]["user"].memberships.first().org_id):
        assert Feature.objects.filter(layer_id=pilot["lyr_farms"]["id"]).count() == 1
    r3 = api.client.post(
        f"/api/v1/layers/{pilot['lyr_farms']['id']}/features",
        data=json.dumps({**body, "status": "draft"}),
        content_type="application/json",
        **headers,
    )
    assert r3.status_code == 422 and r3.json()["type"].endswith("/idempotency-mismatch")


# --- layer delete rule ---------------------------------------------------------------------------


def test_layer_with_features_cannot_be_deleted(people, pilot):
    api = people["manager"]["api"]
    create_farmer(api, pilot)
    assert api.delete(f"/api/v1/layers/{pilot['lyr_farmers']['id']}").status_code == 409


# --- tiles -------------------------------------------------------------------------------


def test_tile_proxy_checks_membership_and_forwards(people, pilot, settings):
    settings.MARTIN_URL = "http://martin.internal:3000"
    api = people["manager"]["api"]
    project_id = pilot["lyr_farms"]["project_id"]
    layer_id = pilot["lyr_farms"]["id"]
    with mock.patch(
        "precisecapture.features.tiles.fetch_tile",
        return_value=(200, b"\x1a\x00mvt", "application/vnd.mapbox-vector-tile"),
    ) as fetch:
        r = api.get(f"/api/v1/projects/{project_id}/tiles/{layer_id}/12/1999/2010.mvt")
        assert (
            r.status_code == 200
            and r.content == b"\x1a\x00mvt"
            and r["Cache-Control"] == "private, max-age=30"
        )
        fetch.assert_called_once_with(
            f"http://martin.internal:3000/tiles_layer/12/1999/2010?project_id={project_id}&layer_id={layer_id}"
        )
        assert (
            people["collector"]["api"]
            .get(f"/api/v1/projects/{project_id}/tiles/{layer_id}/12/1999/2010.mvt")
            .status_code
            == 403
        )
        assert (
            api.get(
                f"/api/v1/projects/{project_id}/tiles/{uuid.uuid4()}/12/1999/2010.mvt"
            ).status_code
            == 404
        )
        assert (
            api.get(f"/api/v1/projects/{project_id}/tiles/{layer_id}/3/999/1.mvt").status_code
            == 404
        )
    with mock.patch(
        "precisecapture.features.tiles.fetch_tile", return_value=(502, b"down", "text/plain")
    ):
        assert (
            api.get(f"/api/v1/projects/{project_id}/tiles/{layer_id}/12/1999/2010.mvt").status_code
            == 502
        )
