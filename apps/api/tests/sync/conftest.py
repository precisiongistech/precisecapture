import uuid
from typing import Any

import pytest

from precisecapture.common.ids import uuid7
from tests.features.conftest import pilot
from tests.projects.conftest import Api, example, login, org, people, project

__all__ = ["Api", "example", "login", "org", "people", "pilot", "project"]

LAT, LON = 6.33, -2.83
D = 100 / 110_574


def square(x: float = LON, y: float = LAT, size: float = D) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]],
    }


FARMER_ATTRS = {
    "full_name": "Ama Mensah",
    "gender": "female",
    "id_type": "none",
    "region": "western_north",
    "district": "juaboso",
    "community": "Juaboso",
    "consent": "yes",
}


def farm_attrs(farmer_id: str, **over: Any) -> dict[str, Any]:
    return {
        "farmer": farmer_id,
        "crop": "cocoa",
        "planting_year": 2018,
        "photos": [str(uuid7())],
        **over,
    }


def change(
    *,
    op: str,
    layer_id: str,
    feature_id: str | None = None,
    base_version: int | None = None,
    geom: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
    changed_fields: list[str] | None = None,
    device_id: str | None = None,
    status: str = "submitted",
    change_id: str | None = None,
) -> dict[str, Any]:
    c: dict[str, Any] = {
        "change_id": change_id or str(uuid7()),
        "op": op,
        "entity": "feature",
        "id": feature_id or str(uuid7()),
        "layer_id": layer_id,
        "base_version": base_version,
        "schema_version": 1,
        "meta": {
            "device_id": device_id or str(uuid.uuid4()),
            "captured_at": "2026-10-24T09:00:00Z",
        },
    }
    if op != "delete":
        c["geom"] = geom
        c["attributes"] = attributes or {}
        c["status"] = status
    if changed_fields is not None:
        c["changed_fields"] = changed_fields
    return c


class Phone:
    """A collector with a registered device, bound to one project."""

    def __init__(self, client: Any, email: str, org_id: str, project_id: str) -> None:
        self.client = client
        self.org_id = org_id
        self.project_id = project_id
        self.device_id = str(uuid7())
        self.email = email
        token = login(client, email)
        r = client.post(
            "/api/v1/devices",
            data={
                "id": self.device_id,
                "platform": "android",
                "model": "Tecno",
                "app_version": "0.1.0",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert r.status_code == 201, r.content
        r = client.post(
            "/api/v1/auth/login",
            data={
                "identifier": email,
                "password": "correct horse battery staple",
                "device_id": self.device_id,
            },
            content_type="application/json",
        )
        assert r.status_code == 200, r.content
        self.api = Api(client, r.json()["access_token"], org_id)

    def push(self, changes: list[dict[str, Any]]) -> Any:
        return self.api.post(
            "/api/v1/sync/push", {"project_id": self.project_id, "changes": changes}
        )

    def pull(self, cursor: int = 0, limit: int = 500) -> Any:
        return self.api.get(
            f"/api/v1/sync/pull?project={self.project_id}&cursor={cursor}&limit={limit}"
        )


@pytest.fixture
def phones(client, people, pilot, project):
    """Two collectors on the project, each with a device."""
    manager = people["manager"]["api"]
    for name in ("collector", "viewer"):
        r = manager.post(
            f"/api/v1/projects/{project.id}/members",
            {"user_id": str(people[name]["user"].id), "role": "collector"},
        )
        assert r.status_code == 201, r.content
    org_id = str(project.org_id)
    return (
        Phone(client, "collector@example.org", org_id, str(project.id)),
        Phone(client, "viewer@example.org", org_id, str(project.id)),
    )
