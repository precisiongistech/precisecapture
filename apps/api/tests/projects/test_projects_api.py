"""Projects, members, layers, ordering, and the project-role rules."""

import pytest

from precisecapture.common.tenancy import tenant_context
from precisecapture.projects.models import Project
from tests.factories import ProjectMemberFactory
from tests.projects.conftest import Api

pytestmark = pytest.mark.django_db

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-2.6, 6.1], [-2.4, 6.1], [-2.4, 6.3], [-2.6, 6.3], [-2.6, 6.1]]],
}


def test_manager_creates_project_with_extent(people, org):
    r = people["manager"]["api"].post(
        "/api/v1/projects",
        {"name": "Western North", "description": "Pilot", "extent": SQUARE, "status": "active"},
    )
    assert r.status_code == 201, r.content
    body = r.json()
    assert (
        body["extent"]["type"] == "Polygon"
        and body["config_version"] == 1
        and body["my_role"] == "manager"
    )
    with tenant_context(org.id):
        extent = Project.objects.get(pk=body["id"]).extent
        assert extent is not None and extent.area > 0


def test_collector_cannot_create_project(people):
    assert people["collector"]["api"].post("/api/v1/projects", {"name": "Nope"}).status_code == 403


def test_invalid_extent_is_422(people):
    bad = {"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]]}  # bow-tie
    r = people["manager"]["api"].post("/api/v1/projects", {"name": "Bad", "extent": bad})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "extent"
    r = people["manager"]["api"].post(
        "/api/v1/projects", {"name": "Bad", "extent": {"type": "Point", "coordinates": [0, 0]}}
    )
    assert r.status_code == 422


def test_visibility_follows_org_role_and_project_membership(people, project, org):
    api_admin, api_collector = people["admin"]["api"], people["collector"]["api"]
    assert [p["id"] for p in api_admin.get("/api/v1/projects").json()] == [str(project.id)]
    assert api_collector.get("/api/v1/projects").json() == []
    assert api_collector.get(f"/api/v1/projects/{project.id}").status_code == 403
    r = api_admin.post(
        f"/api/v1/projects/{project.id}/members",
        {"user_id": str(people["collector"]["user"].id), "role": "collector"},
    )
    assert r.status_code == 201, r.content
    assert [p["my_role"] for p in api_collector.get("/api/v1/projects").json()] == ["collector"]
    assert api_collector.get(f"/api/v1/projects/{project.id}").status_code == 200
    # collectors cannot manage
    assert api_collector.patch(f"/api/v1/projects/{project.id}", {"name": "xx"}).status_code == 403
    assert api_collector.get(f"/api/v1/projects/{project.id}/members").status_code == 403


def test_member_lifecycle_bumps_versions(people, project, org):
    api = people["admin"]["api"]
    user = people["collector"]["user"]
    before = project.config_version
    r = api.post(
        f"/api/v1/projects/{project.id}/members", {"user_id": str(user.id), "assigned_area": SQUARE}
    )
    assert r.status_code == 201 and r.json()["assigned_area"]["type"] == "MultiPolygon"
    assert (
        api.post(f"/api/v1/projects/{project.id}/members", {"user_id": str(user.id)}).status_code
        == 409
    )
    r = api.patch(
        f"/api/v1/projects/{project.id}/members/{user.id}",
        {"role": "manager", "clear_assigned_area": True},
    )
    assert (
        r.status_code == 200
        and r.json()["role"] == "manager"
        and r.json()["assigned_area"] is None
        and r.json()["version"] == 2
    )
    assert len(api.get(f"/api/v1/projects/{project.id}/members").json()) == 1
    assert api.delete(f"/api/v1/projects/{project.id}/members/{user.id}").status_code == 204
    assert api.delete(f"/api/v1/projects/{project.id}/members/{user.id}").status_code == 404
    project.refresh_from_db()
    assert project.config_version == before + 3
    user.refresh_from_db()
    assert user.memberships.get(org=org).version == 4  # add, update, remove each bumped it


def test_member_must_be_in_the_org(people, project):
    from tests.factories import UserFactory

    outsider = UserFactory()
    r = people["admin"]["api"].post(
        f"/api/v1/projects/{project.id}/members", {"user_id": str(outsider.id)}
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not_in_org"


def test_update_project_settings_bumps_config_version_only_when_profile_changes(people, project):
    api = people["manager"]["api"]
    r = api.patch(f"/api/v1/projects/{project.id}", {"description": "new text"})
    assert r.status_code == 200 and r.json()["config_version"] == 1
    r = api.patch(
        f"/api/v1/projects/{project.id}",
        {"settings": {"capture_profile": {"stream": {"intervalMeters": 1}}}},
    )
    assert r.json()["config_version"] == 2


# --- layers --------------------------------------------------------------------------------


def test_layer_crud_and_ordering(people, project, org):
    api = people["manager"]["api"]
    r = api.post(
        f"/api/v1/projects/{project.id}/layers",
        {"name": "Farmers", "key": "lyr_farmers", "geometry_type": "none"},
    )
    assert r.status_code == 201, r.content
    farmers = r.json()
    assert farmers["sort_order"] == 1 and farmers["current_schema_version"] == 0
    r = api.post(
        f"/api/v1/projects/{project.id}/layers",
        {
            "name": "Farms",
            "key": "lyr_farms",
            "geometry_type": "polygon",
            "style": {"fill": "#0a0"},
        },
    )
    farms = r.json()
    assert farms["sort_order"] == 2
    assert (
        api.post(
            f"/api/v1/projects/{project.id}/layers",
            {"name": "Dup", "key": "lyr_farms", "geometry_type": "point"},
        ).status_code
        == 409
    )
    assert (
        api.post(
            f"/api/v1/projects/{project.id}/layers",
            {"name": "Bad", "key": "Bad Key", "geometry_type": "point"},
        ).status_code
        == 422
    )

    r = api.put(
        f"/api/v1/projects/{project.id}/layers/order", {"layer_ids": [farms["id"], farmers["id"]]}
    )
    assert [layer["key"] for layer in r.json()] == ["lyr_farms", "lyr_farmers"]
    assert (
        api.put(
            f"/api/v1/projects/{project.id}/layers/order", {"layer_ids": [farms["id"]]}
        ).status_code
        == 422
    )

    r = api.patch(f"/api/v1/layers/{farms['id']}", {"name": "Cocoa farms"})
    assert r.status_code == 200 and r.json()["name"] == "Cocoa farms"
    assert people["collector"]["api"].get(f"/api/v1/layers/{farms['id']}").status_code == 403
    assert api.delete(f"/api/v1/layers/{farmers['id']}").status_code == 204
    assert [layer["key"] for layer in api.get(f"/api/v1/projects/{project.id}/layers").json()] == [
        "lyr_farms"
    ]
    project.refresh_from_db()
    assert project.config_version == 6  # 2 creates, reorder, rename, delete + 1


def test_layer_capture_profile_is_validated_on_create(people, project):
    api = people["manager"]["api"]
    r = api.post(
        f"/api/v1/projects/{project.id}/layers",
        {
            "name": "Wells",
            "key": "lyr_wells",
            "geometry_type": "point",
            "capture_profile": {"stream": {"intervalMeters": 3}},
        },
    )
    assert r.status_code == 422
    assert r.json()["errors"][0] == {
        "field": "stream",
        "code": "geometry",
        "message": r.json()["errors"][0]["message"],
    }


def test_layers_are_invisible_across_projects_and_orgs(people, project, org):
    from tests.factories import LayerFactory, OrganisationFactory, ProjectFactory

    other_org = OrganisationFactory()
    with tenant_context(other_org.id):
        foreign = LayerFactory(org=other_org, project=ProjectFactory(org=other_org))
    assert people["admin"]["api"].get(f"/api/v1/layers/{foreign.id}").status_code == 404


# --- /me/projects --------------------------------------------------------------------------


def test_me_projects_spans_orgs_and_hides_archived(client, people, project, org):
    from tests.factories import MembershipFactory, OrganisationFactory, ProjectFactory

    user = people["collector"]["user"]
    with tenant_context(org.id):
        ProjectMemberFactory(org=org, project=project, user=user, role="collector")
        ProjectFactory(org=org, name="Archived", status="archived")
        ProjectFactory(org=org, name="Not assigned")
    other = OrganisationFactory(name="Other NGO")
    MembershipFactory(user=user, org=other, role="manager")
    with tenant_context(other.id):
        ProjectFactory(org=other, name="Water points")
    api: Api = people["collector"]["api"]
    r = api.get("/api/v1/me/projects", org=False)
    assert r.status_code == 200, r.content
    rows = {(p["org_name"], p["name"]): p["role"] for p in r.json()}
    assert rows == {
        ("Cocoa Board", "Western North Farm Mapping"): "collector",
        ("Other NGO", "Water points"): "manager",
    }
    assert all("config_version" in p for p in r.json())
