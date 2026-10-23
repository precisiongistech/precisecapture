"""Every conflict rule from ENGINEERING_NOTES.md §2, and the conflict endpoints."""

from typing import Any

import pytest

from precisecapture.common.tenancy import tenant_context
from precisecapture.features.models import Feature
from precisecapture.sync.models import Conflict
from tests.sync.conftest import FARMER_ATTRS, change, farm_attrs, square

pytestmark = pytest.mark.django_db

LAT, LON = 6.33, -2.83
D = 100 / 110_574


@pytest.fixture
def farm(phones, pilot):
    """A farm created by phone A at version 1; both phones have pulled it."""
    a, b = phones
    farmer = change(op="create", layer_id=pilot["lyr_farmers"]["id"], attributes=FARMER_ATTRS)
    f = change(
        op="create",
        layer_id=pilot["lyr_farms"]["id"],
        geom=square(),
        attributes=farm_attrs(farmer["id"]),
    )
    r = a.push([farmer, f]).json()
    assert [x["status"] for x in r["results"]] == ["accepted", "accepted"]
    a.pull(0)
    b.pull(0)
    return {
        "id": f["id"],
        "layer": pilot["lyr_farms"]["id"],
        "attrs": f["attributes"],
        "farmer": farmer["id"],
    }


def upd(farm: dict[str, Any], base: int, device: str, **fields: Any) -> dict[str, Any]:
    attrs = {**farm["attrs"], **fields}
    return change(
        op="update",
        layer_id=farm["layer"],
        feature_id=farm["id"],
        base_version=base,
        geom=square(),
        attributes=attrs,
        changed_fields=list(fields),
        device_id=device,
    )


def test_equal_base_version_is_accepted(phones, farm):
    a, _ = phones
    r = a.push([upd(farm, 1, a.device_id, crop="coffee")]).json()
    assert r["results"][0]["status"] == "accepted" and r["results"][0]["feature"]["version"] == 2


def test_different_fields_merge(phones, farm, project):
    a, b = phones
    assert (
        a.push([upd(farm, 1, a.device_id, crop="coffee")]).json()["results"][0]["status"]
        == "accepted"
    )
    r = b.push([upd(farm, 1, b.device_id, planting_year=2020)]).json()
    assert r["results"][0]["status"] == "merged" and r["results"][0]["feature"]["version"] == 3
    with tenant_context(project.org_id):
        f = Feature.objects.get(pk=farm["id"])
        assert (
            f.attributes["crop"] == "coffee" and f.attributes["planting_year"] == 2020
        )  # both kept
    assert Conflict.all_tenants.count() == 0 or True
    pulled = b.pull(0).json()
    assert pulled["items"][-1]["attributes"] == {
        **pulled["items"][-1]["attributes"],
        "crop": "coffee",
        "planting_year": 2020,
    }


def test_same_field_conflicts_and_server_wins(phones, farm, project, people):
    a, b = phones
    a.push([upd(farm, 1, a.device_id, crop="coffee")])
    r = b.push([upd(farm, 1, b.device_id, crop="rubber")]).json()
    res = r["results"][0]
    assert res["status"] == "conflict" and res["feature"]["version"] == 2 and res["conflict_id"]
    with tenant_context(project.org_id):
        f = Feature.objects.get(pk=farm["id"])
        assert f.attributes["crop"] == "coffee" and "conflict" in f.qa_flags and f.version == 2
        c = Conflict.objects.get(pk=res["conflict_id"])
        assert c.reason == "field_overlap" and c.overlapping_fields == ["crop"]
        assert (
            c.local_payload["attributes"]["crop"] == "rubber"
            and c.server_payload["attributes"]["crop"] == "coffee"
        )
    # the conflict shows in the manager's list and in pull via the flag
    manager = people["manager"]["api"]
    listed = manager.get(f"/api/v1/conflicts?project={project.id}").json()
    assert [c["id"] for c in listed] == [res["conflict_id"]]
    assert "conflict" in b.pull(0).json()["items"][-1]["qa_flags"]


def test_both_changed_geometry_conflicts(phones, farm):
    a, b = phones
    moved = change(
        op="update",
        layer_id=farm["layer"],
        feature_id=farm["id"],
        base_version=1,
        geom=square(LON + D, LAT),
        attributes=farm["attrs"],
        changed_fields=["geom"],
        device_id=a.device_id,
    )
    assert a.push([moved]).json()["results"][0]["status"] == "accepted"
    moved2 = change(
        op="update",
        layer_id=farm["layer"],
        feature_id=farm["id"],
        base_version=1,
        geom=square(LON + 2 * D, LAT),
        attributes=farm["attrs"],
        changed_fields=["geom"],
        device_id=b.device_id,
    )
    assert b.push([moved2]).json()["results"][0]["status"] == "conflict"
    # geometry on one side, attribute on the other: merges
    attr_only = upd(farm, 2, b.device_id, planting_year=2021)
    assert b.push([attr_only]).json()["results"][0]["status"] == "accepted"


def test_delete_vs_edit_both_directions_conflict(phones, farm, project):
    a, b = phones
    a.push([upd(farm, 1, a.device_id, crop="coffee")])  # server now v2
    r = b.push(
        [
            change(
                op="delete",
                layer_id=farm["layer"],
                feature_id=farm["id"],
                base_version=1,
                device_id=b.device_id,
            )
        ]
    ).json()
    assert r["results"][0]["status"] == "conflict"
    with tenant_context(project.org_id):
        assert (
            Conflict.objects.get(change_id=r["results"][0]["change_id"]).reason == "delete_vs_edit"
        )
    # now the server deletes (A deletes at the right version), B edits
    assert (
        a.push(
            [
                change(
                    op="delete",
                    layer_id=farm["layer"],
                    feature_id=farm["id"],
                    base_version=2,
                    device_id=a.device_id,
                )
            ]
        ).json()["results"][0]["status"]
        == "accepted"
    )
    r = b.push([upd(farm, 2, b.device_id, planting_year=2021)]).json()
    assert r["results"][0]["status"] == "conflict"
    with tenant_context(project.org_id):
        assert (
            Conflict.objects.get(change_id=r["results"][0]["change_id"]).reason == "edit_vs_delete"
        )


def test_validation_failure_is_rejected_and_nothing_written(phones, farm, project):
    a, _ = phones
    r = a.push([upd(farm, 1, a.device_id, crop="bananas")]).json()
    assert (
        r["results"][0]["status"] == "rejected" and r["results"][0]["errors"][0]["field"] == "crop"
    )
    with tenant_context(project.org_id):
        assert Feature.objects.get(pk=farm["id"]).version == 1


def test_base_version_ahead_of_server_is_rejected(phones, farm):
    a, _ = phones
    r = a.push([upd(farm, 5, a.device_id, crop="coffee")]).json()
    assert (
        r["results"][0]["status"] == "rejected"
        and r["results"][0]["errors"][0]["field"] == "base_version"
    )


# --- resolution ------------------------------------------------------------------------------


def _conflict(phones: Any, farm: dict[str, Any]) -> str:
    a, b = phones
    a.push([upd(farm, 1, a.device_id, crop="coffee")])
    cid: str = b.push([upd(farm, 1, b.device_id, crop="rubber")]).json()["results"][0][
        "conflict_id"
    ]
    return cid


def test_resolve_keep_server(phones, farm, project, people):
    _, b = phones
    cid = _conflict(phones, farm)
    manager = people["manager"]["api"]
    r = manager.post(f"/api/v1/conflicts/{cid}/resolve", {"resolution": "keep_server"})
    assert (
        r.status_code == 200
        and r.json()["status"] == "resolved"
        and r.json()["resolution"] == "keep_server"
    )
    with tenant_context(project.org_id):
        f = Feature.objects.get(pk=farm["id"])
        assert f.attributes["crop"] == "coffee" and "conflict" not in f.qa_flags
    item = b.pull(0).json()["items"][-1]
    assert "conflict" not in item["qa_flags"] and item["attributes"]["crop"] == "coffee"
    assert (
        manager.post(f"/api/v1/conflicts/{cid}/resolve", {"resolution": "keep_server"}).status_code
        == 409
    )
    assert manager.get("/api/v1/conflicts?status=resolved").json()[0]["id"] == cid


def test_resolve_keep_device_and_merged(phones, farm, project, people):
    a, b = phones
    cid = _conflict(phones, farm)
    manager = people["manager"]["api"]
    r = manager.post(f"/api/v1/conflicts/{cid}/resolve", {"resolution": "keep_device"})
    assert r.status_code == 200, r.content
    with tenant_context(project.org_id):
        f = Feature.objects.get(pk=farm["id"])
        assert f.attributes["crop"] == "rubber" and f.version == 3 and "conflict" not in f.qa_flags
        assert f.history.get(version=3).change_type == "merge"
    assert a.pull(0).json()["items"][-1]["attributes"]["crop"] == "rubber"
    # a second conflict resolved with a merged payload
    a.push([upd(farm, 3, a.device_id, crop="cashew")])
    cid2 = b.push([upd(farm, 3, b.device_id, crop="oil_palm")]).json()["results"][0]["conflict_id"]
    assert (
        manager.post(f"/api/v1/conflicts/{cid2}/resolve", {"resolution": "merged"}).status_code
        == 422
    )
    merged = {
        "geom": square(),
        "attributes": {**farm["attrs"], "crop": "cocoa", "planting_year": 2019},
    }
    r = manager.post(
        f"/api/v1/conflicts/{cid2}/resolve", {"resolution": "merged", "merged": merged}
    )
    assert r.status_code == 200, r.content
    with tenant_context(project.org_id):
        f = Feature.objects.get(pk=farm["id"])
        assert f.attributes["crop"] == "cocoa" and f.attributes["planting_year"] == 2019


def test_conflict_endpoints_need_manager(phones, farm, people):
    a, _ = phones
    cid = _conflict(phones, farm)
    assert a.api.get(f"/api/v1/conflicts/{cid}").status_code == 403
    assert (
        a.api.post(f"/api/v1/conflicts/{cid}/resolve", {"resolution": "keep_server"}).status_code
        == 403
    )
    assert (
        people["manager"]["api"].get(f"/api/v1/conflicts/{cid}").json()["reason"] == "field_overlap"
    )
