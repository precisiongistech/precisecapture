"""Login, refresh rotation, logout, /me, devices and the tenant auth class."""

import uuid
from datetime import timedelta
from typing import Any

import jwt
import pytest
from django.conf import settings as dj_settings
from django.db import connection
from django.http import HttpRequest
from django.test import Client
from django.urls import path
from django.utils import timezone
from ninja import NinjaAPI

from config.api import api as main_api
from precisecapture.accounts.models import Device, RefreshToken
from precisecapture.accounts.tokens import ALGORITHM
from precisecapture.common.auth import current_org, tenant_auth
from precisecapture.common.errors import register_exception_handlers
from precisecapture.common.tenancy import current_org_id
from tests.factories import (
    DeviceFactory,
    MembershipFactory,
    OrganisationFactory,
    PhoneUserFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

PASSWORD = "correct horse battery staple"

# A tenant-protected endpoint exists only from M3 on, so this module mounts one for the test.
probe = NinjaAPI(urls_namespace="tenant-probe")
register_exception_handlers(probe)


@probe.get("/probe", auth=tenant_auth)
def tenant_probe(request: HttpRequest) -> dict[str, Any]:
    with connection.cursor() as cur:
        cur.execute("SELECT current_setting('app.current_org_id', true)")
        db_value = cur.fetchone()[0]
    return {
        "org": str(current_org(request).id),
        "db_setting": db_value,
        "ctx": str(current_org_id()),
    }


urlpatterns = [path("api/v1/", main_api.urls), path("t/", probe.urls)]
handler404 = "precisecapture.common.errors.handler404"


@pytest.fixture
def client(settings) -> Client:
    settings.ROOT_URLCONF = __name__
    return Client()


def login(client: Client, identifier: str, password: str = PASSWORD, **extra: Any) -> Any:
    return client.post(
        "/api/v1/auth/login",
        data={"identifier": identifier, "password": password, **extra},
        content_type="application/json",
    )


def bearer(token: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


# --- login ---------------------------------------------------------------------------------


def test_login_returns_pair_and_me_works(client):
    user = UserFactory(email="ama@example.org", name="Ama")
    m = MembershipFactory(user=user, role="admin")
    r = login(client, "Ama@Example.org")
    assert r.status_code == 200, r.content
    body = r.json()
    assert (
        body["token_type"] == "Bearer" and body["expires_in"] == dj_settings.JWT_ACCESS_TTL_SECONDS
    )
    me = client.get("/api/v1/me", **bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "ama@example.org"
    assert me.json()["memberships"] == [
        {
            "org_id": str(m.org_id),
            "org_name": m.org.name,
            "org_slug": m.org.slug,
            "role": "admin",
            "version": 1,
        }
    ]
    assert me.json()["device_id"] is None
    user.refresh_from_db()
    assert user.last_login_at is not None


def test_login_with_phone_identifier(client):
    PhoneUserFactory(phone="+233241234567")
    assert login(client, "+233 24 123 4567").status_code == 200


@pytest.mark.parametrize("identifier", ["ama@example.org", "nobody@example.org"])
def test_login_wrong_password_or_unknown_user_is_401_problem(client, identifier):
    UserFactory(email="ama@example.org")
    r = login(client, identifier, password="wrong")
    assert r.status_code == 401
    assert r["Content-Type"] == "application/problem+json"
    assert r.json()["detail"] == "Invalid credentials"


def test_disabled_user_cannot_login(client):
    UserFactory(email="off@example.org", status="disabled")
    assert login(client, "off@example.org").status_code == 401


def test_login_is_rate_limited_per_identifier(client, settings):
    settings.RATE_LIMIT_LOGIN_PER_IDENTIFIER = "3/900"
    UserFactory(email="ama@example.org")
    for _ in range(3):
        assert login(client, "ama@example.org", password="wrong").status_code == 401
    r = login(client, "ama@example.org")  # correct password, but over the limit
    assert r.status_code == 429
    assert r.json()["type"].endswith("/rate-limited")


def test_successful_login_resets_the_identifier_limit(client, settings):
    settings.RATE_LIMIT_LOGIN_PER_IDENTIFIER = "3/900"
    UserFactory(email="ama@example.org")
    login(client, "ama@example.org", password="wrong")
    login(client, "ama@example.org", password="wrong")
    assert login(client, "ama@example.org").status_code == 200
    login(client, "ama@example.org", password="wrong")
    login(client, "ama@example.org", password="wrong")
    assert login(client, "ama@example.org").status_code == 200


# --- access tokens -------------------------------------------------------------------------


def test_me_without_or_with_bad_token_is_401_problem(client):
    assert client.get("/api/v1/me").status_code == 401
    r = client.get("/api/v1/me", **bearer("garbage"))
    assert r.status_code == 401 and r["Content-Type"] == "application/problem+json"


def test_expired_access_token_is_rejected(client):
    user = UserFactory()
    past = timezone.now() - timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(user.id), "iat": int(past.timestamp()), "exp": int(past.timestamp()) + 60},
        dj_settings.JWT_SIGNING_KEY,
        algorithm=ALGORITHM,
    )
    assert client.get("/api/v1/me", **bearer(token)).status_code == 401


def test_token_signed_with_another_key_is_rejected(client):
    user = UserFactory()
    now = timezone.now()
    token = jwt.encode(
        {"sub": str(user.id), "iat": int(now.timestamp()), "exp": int(now.timestamp()) + 60},
        "not-the-key",
        algorithm=ALGORITHM,
    )
    assert client.get("/api/v1/me", **bearer(token)).status_code == 401


def test_disabled_after_login_is_rejected_on_next_request(client):
    user = UserFactory(email="ama@example.org")
    token = login(client, "ama@example.org").json()["access_token"]
    user.status = "disabled"
    user.save()
    assert client.get("/api/v1/me", **bearer(token)).status_code == 401


# --- refresh rotation ----------------------------------------------------------------------


def refresh(client: Client, token: str) -> Any:
    return client.post(
        "/api/v1/auth/refresh", data={"refresh_token": token}, content_type="application/json"
    )


def test_refresh_rotates_and_reuse_revokes_the_family(client):
    UserFactory(email="ama@example.org")
    first = login(client, "ama@example.org").json()["refresh_token"]
    second = refresh(client, first)
    assert second.status_code == 200
    second_token = second.json()["refresh_token"]
    assert second_token != first
    assert client.get("/api/v1/me", **bearer(second.json()["access_token"])).status_code == 200

    # Replay of the rotated token: rejected, and the current token dies with it.
    replay = refresh(client, first)
    assert replay.status_code == 401
    assert "already used" in replay.json()["detail"]
    assert refresh(client, second_token).status_code == 401
    assert RefreshToken.objects.filter(revoked_at__isnull=True).count() == 0


def test_refresh_with_unknown_token_is_401(client):
    assert refresh(client, "nope").status_code == 401


def test_logout_revokes_the_chain_and_is_idempotent(client):
    UserFactory(email="ama@example.org")
    pair = login(client, "ama@example.org").json()
    r = client.post(
        "/api/v1/auth/logout",
        data={"refresh_token": pair["refresh_token"]},
        content_type="application/json",
    )
    assert r.status_code == 204
    assert refresh(client, pair["refresh_token"]).status_code == 401
    r = client.post(
        "/api/v1/auth/logout",
        data={"refresh_token": pair["refresh_token"]},
        content_type="application/json",
    )
    assert r.status_code == 204


def test_expired_refresh_token_is_rejected(client):
    UserFactory(email="ama@example.org")
    raw = login(client, "ama@example.org").json()["refresh_token"]
    RefreshToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert refresh(client, raw).status_code == 401


# --- devices -------------------------------------------------------------------------------


def test_register_device_keeps_client_id_and_is_idempotent(client):
    UserFactory(email="ama@example.org")
    access = login(client, "ama@example.org").json()["access_token"]
    device_id = str(uuid.uuid4())
    body = {
        "id": device_id,
        "platform": "android",
        "model": "Tecno Spark 10",
        "os_version": "13",
        "app_version": "0.1.0",
    }
    r = client.post("/api/v1/devices", data=body, content_type="application/json", **bearer(access))
    assert r.status_code == 201 and r.json()["id"] == device_id
    r = client.post(
        "/api/v1/devices",
        data={**body, "app_version": "0.2.0"},
        content_type="application/json",
        **bearer(access),
    )
    assert r.status_code == 201 and r.json()["app_version"] == "0.2.0"
    assert Device.objects.count() == 1
    listed = client.get("/api/v1/devices", **bearer(access)).json()
    assert [d["id"] for d in listed] == [device_id]


def test_cannot_claim_another_users_device_id(client):
    other = DeviceFactory()
    UserFactory(email="ama@example.org")
    access = login(client, "ama@example.org").json()["access_token"]
    r = client.post(
        "/api/v1/devices",
        data={"id": str(other.id), "platform": "ios"},
        content_type="application/json",
        **bearer(access),
    )
    assert r.status_code == 404
    assert Device.objects.get(pk=other.id).user == other.user


def test_device_bound_login_and_revocation(client):
    user = UserFactory(email="ama@example.org")
    device = DeviceFactory(user=user)
    pair = login(client, "ama@example.org", device_id=str(device.id)).json()
    me = client.get("/api/v1/me", **bearer(pair["access_token"])).json()
    assert me["device_id"] == str(device.id)
    assert RefreshToken.objects.get().device == device

    r = client.delete(f"/api/v1/devices/{device.id}", **bearer(pair["access_token"]))
    assert r.status_code == 204
    assert refresh(client, pair["refresh_token"]).status_code == 401
    assert login(client, "ama@example.org", device_id=str(device.id)).status_code == 401


def test_login_with_unknown_device_is_rejected(client):
    UserFactory(email="ama@example.org")
    assert login(client, "ama@example.org", device_id=str(uuid.uuid4())).status_code == 401


def test_revoking_a_device_you_do_not_own_is_404(client):
    other = DeviceFactory()
    UserFactory(email="ama@example.org")
    access = login(client, "ama@example.org").json()["access_token"]
    assert client.delete(f"/api/v1/devices/{other.id}", **bearer(access)).status_code == 404


# --- tenant auth ---------------------------------------------------------------------------


def test_tenant_endpoint_requires_the_org_header(client):
    UserFactory(email="ama@example.org")
    access = login(client, "ama@example.org").json()["access_token"]
    r = client.get("/t/probe", **bearer(access))
    assert r.status_code == 400 and r.json()["type"].endswith("/missing-org-header")
    r = client.get("/t/probe", **bearer(access), HTTP_X_ORG_ID="not-a-uuid")
    assert r.status_code == 400


def test_non_member_gets_403(client):
    user = UserFactory(email="ama@example.org")
    MembershipFactory(user=user)
    other_org = OrganisationFactory()
    access = login(client, "ama@example.org").json()["access_token"]
    r = client.get("/t/probe", **bearer(access), HTTP_X_ORG_ID=str(other_org.id))
    assert r.status_code == 403
    assert r["Content-Type"] == "application/problem+json"


def test_member_request_runs_with_the_tenant_set_in_the_database(client):
    user = UserFactory(email="ama@example.org")
    m1 = MembershipFactory(user=user)
    m2 = MembershipFactory(user=user)
    access = login(client, "ama@example.org").json()["access_token"]
    for m in (m1, m2):
        r = client.get("/t/probe", **bearer(access), HTTP_X_ORG_ID=str(m.org_id))
        assert r.status_code == 200, r.content
        assert r.json() == {"org": str(m.org_id), "db_setting": str(m.org_id), "ctx": str(m.org_id)}
    # The middleware clears the contextvar once the request is over.
    assert current_org_id() is None


def test_tenant_endpoint_without_token_is_401(client):
    org = OrganisationFactory()
    assert client.get("/t/probe", HTTP_X_ORG_ID=str(org.id)).status_code == 401
