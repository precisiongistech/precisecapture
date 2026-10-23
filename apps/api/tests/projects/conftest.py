import json
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings as dj_settings
from django.test import Client

from precisecapture.common.tenancy import tenant_context
from tests.factories import MembershipFactory, OrganisationFactory, ProjectFactory, UserFactory

PASSWORD = "correct horse battery staple"
EXAMPLES = Path(dj_settings.SCHEMA_DIR) / "examples"


def example(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((EXAMPLES / name).read_text())
    return data


class Api:
    """A thin client bound to one user and org: api.get(path), api.post(path, json)."""

    def __init__(self, client: Client, token: str, org_id: str) -> None:
        self.client, self.token, self.org_id = client, token, org_id

    def _h(self, org: bool = True) -> dict[str, Any]:
        h = {"HTTP_AUTHORIZATION": f"Bearer {self.token}"}
        if org:
            h["HTTP_X_ORG_ID"] = self.org_id
        return h

    def get(self, path: str, org: bool = True, **extra: Any) -> Any:
        return self.client.get(path, **self._h(org), **extra)

    def post(self, path: str, data: Any = None, org: bool = True) -> Any:
        return self.client.post(
            path, data=json.dumps(data or {}), content_type="application/json", **self._h(org)
        )

    def put(self, path: str, data: Any = None) -> Any:
        return self.client.put(
            path, data=json.dumps(data or {}), content_type="application/json", **self._h()
        )

    def patch(self, path: str, data: Any = None) -> Any:
        return self.client.patch(
            path, data=json.dumps(data or {}), content_type="application/json", **self._h()
        )

    def delete(self, path: str) -> Any:
        return self.client.delete(path, **self._h())


def login(client: Client, email: str) -> str:
    r = client.post(
        "/api/v1/auth/login",
        data={"identifier": email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    return str(r.json()["access_token"])


@pytest.fixture
def org():
    return OrganisationFactory(
        name="Cocoa Board", settings={"capture_defaults": {"gps": {"maxAccuracyMeters": 8}}}
    )


@pytest.fixture
def people(client, org):
    """admin (org admin), manager (org manager), collector and viewer (org collectors)."""
    out: dict[str, Any] = {}
    for name, org_role in (
        ("admin", "admin"),
        ("manager", "manager"),
        ("collector", "collector"),
        ("viewer", "collector"),
    ):
        user = UserFactory(email=f"{name}@example.org", name=name.title())
        MembershipFactory(user=user, org=org, role=org_role)
        out[name] = {"user": user, "api": Api(client, login(client, user.email), str(org.id))}
    return out


@pytest.fixture
def project(org):
    with tenant_context(org.id):
        return ProjectFactory(
            org=org,
            name="Western North Farm Mapping",
            settings={"capture_profile": {"stream": {"intervalMeters": 3}}},
        )
