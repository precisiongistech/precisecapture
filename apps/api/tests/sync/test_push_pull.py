"""Push/pull: idempotent replay, ordering, paging, review in pull, gzip, isolation, limits."""

import gzip
import json
import uuid

import pytest

from precisecapture.common.tenancy import tenant_context
from precisecapture.features.models import Feature, FeatureHistory
from precisecapture.sync.models import AppliedChange, ChangeLog, SyncCursor
from tests.sync.conftest import FARMER_ATTRS, change, farm_attrs, square

pytestmark = pytest.mark.django_db


def test_push_create_and_pull_from_zero(phones, pilot, project):
    a, _ = phones
    farmers, farms = pilot["lyr_farmers"]["id"], pilot["lyr_farms"]["id"]
    farmer = change(op="create", layer_id=farmers, attributes=FARMER_ATTRS, device_id=a.device_id)
    farm = change(
        op="create",
        layer_id=farms,
        geom=square(),
        attributes=farm_attrs(farmer["id"]),
        device_id=a.device_id,
    )
    r = a.push([farmer, farm])
    assert r.status_code == 200, r.content
    body = r.json()
    assert [x["status"] for x in body["results"]] == ["accepted", "accepted"]
    assert body["results"][1]["feature"] == {"id": farm["id"], "version": 1}
    project.refresh_from_db()
    assert body["last_seq"] == 2 and body["config_version"] == project.config_version
    r = a.pull(0)
    assert r.status_code == 200, r.content
    pulled = r.json()
    assert [i["id"] for i in pulled["items"]] == [farmer["id"], farm["id"]]
    assert [i["seq"] for i in pulled["items"]] == [1, 2]
    assert pulled["next_cursor"] == 2 and pulled["has_more"] is False
    farm_item = pulled["items"][1]
    assert farm_item["computed"]["area_m2"] == pytest.approx(10_000, rel=0.002)
    assert farm_item["attributes"]["area_ha"] == pytest.approx(1.0, rel=0.002)
    assert "raw_track" not in farm_item and farm_item["deleted"] is False
    with tenant_context(project.org_id):
        cursor = SyncCursor.objects.get(device_id=a.device_id)
        assert (
            cursor.pushed_changes == 2 and cursor.last_pulled_seq == 2 and cursor.pulled_items == 2
        )


def test_replaying_a_batch_gives_duplicates_and_no_new_versions(phones, pilot, project):
    a, _ = phones
    farmer = change(op="create", layer_id=pilot["lyr_farmers"]["id"], attributes=FARMER_ATTRS)
    first = a.push([farmer]).json()
    second = a.push([farmer]).json()
    assert second["results"][0]["status"] == "duplicate"
    assert second["results"][0]["feature"] == first["results"][0]["feature"]
    assert second["last_seq"] == first["last_seq"] == 1
    with tenant_context(project.org_id):
        assert Feature.objects.get(pk=farmer["id"]).version == 1
        assert FeatureHistory.objects.filter(feature_id=farmer["id"]).count() == 1
        assert ChangeLog.objects.count() == 1 and AppliedChange.objects.count() == 1
    # same id, different payload, new change_id -> rejected
    other = change(
        op="create",
        layer_id=pilot["lyr_farmers"]["id"],
        feature_id=farmer["id"],
        attributes={**FARMER_ATTRS, "community": "Bodi"},
    )
    assert a.push([other]).json()["results"][0]["status"] == "rejected"
    # same id, same payload, new change_id -> duplicate
    same = change(
        op="create",
        layer_id=pilot["lyr_farmers"]["id"],
        feature_id=farmer["id"],
        attributes=FARMER_ATTRS,
    )
    assert a.push([same]).json()["results"][0]["status"] == "duplicate"


def test_rejected_change_does_not_poison_the_batch(phones, pilot, project):
    a, _ = phones
    good = change(op="create", layer_id=pilot["lyr_farmers"]["id"], attributes=FARMER_ATTRS)
    bad = change(
        op="create", layer_id=pilot["lyr_farmers"]["id"], attributes={**FARMER_ATTRS, "gender": "x"}
    )
    unknown_layer = change(op="create", layer_id=str(uuid.uuid4()), attributes={})
    r = a.push([bad, good, unknown_layer]).json()
    assert [x["status"] for x in r["results"]] == ["rejected", "accepted", "rejected"]
    assert r["results"][0]["errors"][0]["field"] == "gender"
    assert r["results"][2]["errors"][0]["code"] == "unknown_layer"
    assert r["last_seq"] == 1
    with tenant_context(project.org_id):
        assert Feature.objects.count() == 1
        assert AppliedChange.objects.count() == 3  # rejections are remembered too


def test_update_and_delete_then_pull_collapses_to_latest(phones, pilot, project):
    a, _ = phones
    farmers = pilot["lyr_farmers"]["id"]
    farmer = change(op="create", layer_id=farmers, attributes=FARMER_ATTRS)
    a.push([farmer])
    upd = change(
        op="update",
        layer_id=farmers,
        feature_id=farmer["id"],
        base_version=1,
        attributes={**FARMER_ATTRS, "community": "Bodi"},
        changed_fields=["community"],
    )
    r = a.push([upd]).json()
    assert r["results"][0]["status"] == "accepted" and r["results"][0]["feature"]["version"] == 2
    pulled = a.pull(0).json()
    assert (
        len(pulled["items"]) == 1
        and pulled["items"][0]["version"] == 2
        and pulled["items"][0]["seq"] == 2
    )
    assert pulled["items"][0]["attributes"]["community"] == "Bodi"
    dele = change(op="delete", layer_id=farmers, feature_id=farmer["id"], base_version=2)
    r = a.push([dele]).json()
    assert r["results"][0]["status"] == "accepted"
    pulled = a.pull(2).json()
    assert (
        pulled["items"][0]["deleted"] is True
        and pulled["items"][0]["attributes"] == {}
        and pulled["items"][0]["version"] == 3
    )
    assert a.push([dele]).json()["results"][0]["status"] == "duplicate"


def test_pull_pages_across_the_limit_without_gaps(phones, pilot, project):
    a, _ = phones
    farmers = pilot["lyr_farmers"]["id"]
    ids = []
    for i in range(7):
        c = change(
            op="create", layer_id=farmers, attributes={**FARMER_ATTRS, "full_name": f"Farmer {i}"}
        )
        ids.append(c["id"])
        assert a.push([c]).json()["results"][0]["status"] == "accepted"
    seen: list[int] = []
    cursor = 0
    pages = 0
    while True:
        page = a.pull(cursor, limit=3).json()
        pages += 1
        seen += [i["seq"] for i in page["items"]]
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert pages == 3 and seen == [1, 2, 3, 4, 5, 6, 7]
    project.refresh_from_db()
    assert a.pull(7).json() == {
        "items": [],
        "next_cursor": 7,
        "has_more": False,
        "config_version": project.config_version,
    }


def test_review_and_web_edits_reach_the_next_pull(phones, pilot, project, people):
    a, _ = phones
    farmers = pilot["lyr_farmers"]["id"]
    farmer = change(op="create", layer_id=farmers, attributes=FARMER_ATTRS)
    a.push([farmer])
    manager = people["manager"]["api"]
    r = manager.post(
        f"/api/v1/features/{farmer['id']}/review",
        {"action": "send_back", "note": "Add the ID number"},
    )
    assert r.status_code == 200
    manager.patch(
        f"/api/v1/features/{farmer['id']}",
        {"attributes": {**FARMER_ATTRS, "community": "Bodi"}, "base_version": 2},
    )
    pulled = a.pull(1).json()
    assert len(pulled["items"]) == 1
    item = pulled["items"][0]
    assert item["status"] == "sent_back" and item["review_note"] == "Add the ID number"
    assert item["attributes"]["community"] == "Bodi" and item["version"] == 3 and item["seq"] == 3


def test_gzip_push_is_accepted(phones, pilot):
    a, _ = phones
    farmer = change(op="create", layer_id=pilot["lyr_farmers"]["id"], attributes=FARMER_ATTRS)
    body = gzip.compress(json.dumps({"project_id": a.project_id, "changes": [farmer]}).encode())
    r = a.client.post(
        "/api/v1/sync/push",
        data=body,
        content_type="application/json",
        HTTP_CONTENT_ENCODING="gzip",
        **a.api._h(),
    )
    assert r.status_code == 200, r.content
    assert r.json()["results"][0]["status"] == "accepted"


def test_more_than_200_changes_is_422(phones, pilot):
    a, _ = phones
    changes = [
        change(op="create", layer_id=pilot["lyr_farmers"]["id"], attributes=FARMER_ATTRS)
        for _ in range(201)
    ]
    assert a.push(changes).status_code == 422


def test_pull_and_push_are_tenant_isolated(phones, pilot, project, people, client):
    a, _ = phones
    farmer = change(op="create", layer_id=pilot["lyr_farmers"]["id"], attributes=FARMER_ATTRS)
    a.push([farmer])
    from tests.factories import MembershipFactory, OrganisationFactory, UserFactory
    from tests.projects.conftest import Api, login

    other = OrganisationFactory()
    outsider = UserFactory(email="out@example.org")
    MembershipFactory(user=outsider, org=other, role="owner")
    out = Api(client, login(client, "out@example.org"), str(other.id))
    assert out.get(f"/api/v1/sync/pull?project={project.id}&cursor=0").status_code == 404
    assert (
        out.post("/api/v1/sync/push", {"project_id": str(project.id), "changes": []}).status_code
        == 404
    )
    # a viewer-only project member can pull but not push
    manager = people["manager"]["api"]
    manager.patch(
        f"/api/v1/projects/{project.id}/members/{people['viewer']['user'].id}", {"role": "viewer"}
    )
    _, b = phones
    assert b.pull(0).status_code == 200
    assert (
        b.push(
            [change(op="create", layer_id=pilot["lyr_farmers"]["id"], attributes=FARMER_ATTRS)]
        ).status_code
        == 403
    )


def test_push_requires_known_feature_for_update(phones, pilot):
    a, _ = phones
    upd = change(
        op="update",
        layer_id=pilot["lyr_farmers"]["id"],
        base_version=1,
        attributes=FARMER_ATTRS,
        changed_fields=["community"],
    )
    r = a.push([upd]).json()
    assert (
        r["results"][0]["status"] == "rejected"
        and r["results"][0]["errors"][0]["code"] == "not_found"
    )
