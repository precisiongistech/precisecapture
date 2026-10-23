"""Organisation admin: create, update, members, roles, invitations, permission helpers."""

import re
from typing import Any

import pytest
from django.core import mail
from django.test import Client

from precisecapture.orgs.models import Invitation, Membership, Organisation
from tests.factories import MembershipFactory, OrganisationFactory, UserFactory

pytestmark = pytest.mark.django_db

PASSWORD = "correct horse battery staple"


def token_for(client: Client, email: str) -> str:
    r = client.post(
        "/api/v1/auth/login",
        data={"identifier": email, "password": PASSWORD},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    return str(r.json()["access_token"])


def hdr(token: str, org: Organisation | None = None) -> dict[str, Any]:
    h = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    if org is not None:
        h["HTTP_X_ORG_ID"] = str(org.id)
    return h


@pytest.fixture
def org_with_roles(client):
    """One org with an owner, an admin, a manager and a collector, each logged in."""
    org = OrganisationFactory(name="Cocoa Board")
    people: dict[str, Any] = {}
    for role in ("owner", "admin", "manager", "collector"):
        user = UserFactory(email=f"{role}@example.org", name=role.title())
        MembershipFactory(user=user, org=org, role=role)
        people[role] = {"user": user, "token": token_for(client, user.email)}
    return org, people


# --- create / read / update -------------------------------------------------------------


def test_create_org_makes_creator_owner(client):
    UserFactory(email="ama@example.org")
    token = token_for(client, "ama@example.org")
    r = client.post(
        "/api/v1/orgs",
        data={
            "name": "Western North Co-op",
            "country": "gh",
            "settings": {"capture_defaults": {"gps": {"maxAccuracyMeters": 5}}},
        },
        content_type="application/json",
        **hdr(token),
    )
    assert r.status_code == 201, r.content
    body = r.json()
    assert (
        body["slug"] == "western-north-co-op"
        and body["country"] == "GH"
        and body["plan"] == "trial"
    )
    m = Membership.objects.get(org_id=body["id"])
    assert m.role == "owner" and m.user.email == "ama@example.org"
    me = client.get("/api/v1/me", **hdr(token)).json()
    assert me["memberships"][0]["role"] == "owner"


def test_get_org_requires_matching_header(client, org_with_roles):
    org, people = org_with_roles
    other = OrganisationFactory()
    token = people["collector"]["token"]
    assert client.get(f"/api/v1/orgs/{org.id}", **hdr(token, org)).status_code == 200
    r = client.get(f"/api/v1/orgs/{other.id}", **hdr(token, org))
    assert r.status_code == 403
    assert client.get(f"/api/v1/orgs/{org.id}", **hdr(token)).status_code == 400  # no header


def test_update_org_needs_admin(client, org_with_roles):
    org, people = org_with_roles
    r = client.patch(
        f"/api/v1/orgs/{org.id}",
        data={"name": "Renamed"},
        content_type="application/json",
        **hdr(people["manager"]["token"], org),
    )
    assert r.status_code == 403
    r = client.patch(
        f"/api/v1/orgs/{org.id}",
        data={
            "name": "Renamed",
            "slug": "renamed-org",
            "settings": {"capture_defaults": {"stream": {"intervalMeters": 3}}},
        },
        content_type="application/json",
        **hdr(people["admin"]["token"], org),
    )
    assert r.status_code == 200, r.content
    org.refresh_from_db()
    assert org.name == "Renamed" and org.slug == "renamed-org"
    assert org.capture_defaults == {"stream": {"intervalMeters": 3}}


def test_slug_must_be_unique(client, org_with_roles):
    org, people = org_with_roles
    OrganisationFactory(slug="taken")
    r = client.patch(
        f"/api/v1/orgs/{org.id}",
        data={"slug": "taken"},
        content_type="application/json",
        **hdr(people["owner"]["token"], org),
    )
    assert r.status_code == 409


# --- members -----------------------------------------------------------------------------


def test_list_members_needs_manager(client, org_with_roles):
    org, people = org_with_roles
    assert (
        client.get(
            f"/api/v1/orgs/{org.id}/members", **hdr(people["collector"]["token"], org)
        ).status_code
        == 403
    )
    r = client.get(f"/api/v1/orgs/{org.id}/members", **hdr(people["manager"]["token"], org))
    assert r.status_code == 200
    assert sorted(m["role"] for m in r.json()) == ["admin", "collector", "manager", "owner"]
    assert {"user_id", "email", "phone", "name", "role", "status", "joined_at"} <= set(r.json()[0])


def test_admin_can_change_roles_below_owner_but_not_grant_owner(client, org_with_roles):
    org, people = org_with_roles
    collector_id = people["collector"]["user"].id
    url = f"/api/v1/orgs/{org.id}/members/{collector_id}"
    r = client.patch(
        url,
        data={"role": "manager"},
        content_type="application/json",
        **hdr(people["admin"]["token"], org),
    )
    assert r.status_code == 200 and r.json()["role"] == "manager"
    assert Membership.objects.get(user_id=collector_id).version == 2
    r = client.patch(
        url,
        data={"role": "owner"},
        content_type="application/json",
        **hdr(people["admin"]["token"], org),
    )
    assert r.status_code == 403
    r = client.patch(
        url,
        data={"role": "owner"},
        content_type="application/json",
        **hdr(people["owner"]["token"], org),
    )
    assert r.status_code == 200


def test_admin_cannot_demote_an_owner(client, org_with_roles):
    org, people = org_with_roles
    owner_id = people["owner"]["user"].id
    r = client.patch(
        f"/api/v1/orgs/{org.id}/members/{owner_id}",
        data={"role": "viewer"},
        content_type="application/json",
        **hdr(people["admin"]["token"], org),
    )
    assert r.status_code == 403


def test_last_owner_cannot_be_demoted_or_removed(client, org_with_roles):
    org, people = org_with_roles
    owner_id = people["owner"]["user"].id
    token = people["owner"]["token"]
    r = client.patch(
        f"/api/v1/orgs/{org.id}/members/{owner_id}",
        data={"role": "admin"},
        content_type="application/json",
        **hdr(token, org),
    )
    assert r.status_code == 409
    assert (
        client.delete(f"/api/v1/orgs/{org.id}/members/{owner_id}", **hdr(token, org)).status_code
        == 409
    )


def test_remove_member_and_self_removal(client, org_with_roles):
    org, people = org_with_roles
    collector_id = people["collector"]["user"].id
    # a collector cannot remove someone else
    assert (
        client.delete(
            f"/api/v1/orgs/{org.id}/members/{people['manager']['user'].id}",
            **hdr(people["collector"]["token"], org),
        ).status_code
        == 403
    )
    # but may leave
    assert (
        client.delete(
            f"/api/v1/orgs/{org.id}/members/{collector_id}",
            **hdr(people["collector"]["token"], org),
        ).status_code
        == 204
    )
    assert not Membership.objects.filter(user_id=collector_id).exists()
    # admin removes the manager; unknown member is 404
    assert (
        client.delete(
            f"/api/v1/orgs/{org.id}/members/{people['manager']['user'].id}",
            **hdr(people["admin"]["token"], org),
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/orgs/{org.id}/members/{collector_id}", **hdr(people["admin"]["token"], org)
        ).status_code
        == 404
    )


# --- invitations -------------------------------------------------------------------------


def invite(client: Client, org: Organisation, token: str, **payload: Any) -> Any:
    return client.post(
        f"/api/v1/orgs/{org.id}/invitations",
        data=payload,
        content_type="application/json",
        **hdr(token, org),
    )


def invitation_token_from_email() -> str:
    match = re.search(r"/invitations/([A-Za-z0-9_-]+)", str(mail.outbox[-1].body))
    assert match, mail.outbox[-1].body
    return match.group(1)


def test_invite_new_person_by_email_and_accept_with_new_account(client, org_with_roles):
    org, people = org_with_roles
    r = invite(
        client, org, people["admin"]["token"], email="New.Person@Example.org", role="collector"
    )
    assert r.status_code == 201, r.content
    assert r.json()["email"] == "new.person@example.org" and "token" not in r.json()
    assert mail.outbox[-1].to == ["new.person@example.org"]
    raw = invitation_token_from_email()

    preview = client.get(f"/api/v1/invitations/{raw}").json()
    assert preview == {
        "org_name": "Cocoa Board",
        "role": "collector",
        "destination": "new.person@example.org",
        "account_exists": False,
        "expires_at": preview["expires_at"],
    }
    # no password -> 422
    r = client.post(
        f"/api/v1/invitations/{raw}/accept",
        data={"name": "New Person"},
        content_type="application/json",
    )
    assert r.status_code == 422
    r = client.post(
        f"/api/v1/invitations/{raw}/accept",
        data={"name": "New Person", "password": "a-strong-password"},
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["role"] == "collector" and body["access_token"] and body["refresh_token"]
    me = client.get("/api/v1/me", **hdr(body["access_token"])).json()
    assert me["user"]["email"] == "new.person@example.org" and me["memberships"][0][
        "org_id"
    ] == str(org.id)
    # single use
    assert client.get(f"/api/v1/invitations/{raw}").status_code == 404


def test_invite_existing_user_accepts_while_logged_in(client, org_with_roles):
    org, people = org_with_roles
    existing = UserFactory(email="kofi@example.org")
    invite(client, org, people["owner"]["token"], email="kofi@example.org", role="manager")
    raw = invitation_token_from_email()
    assert client.get(f"/api/v1/invitations/{raw}").json()["account_exists"] is True
    # anonymous acceptance is refused because the account exists
    r = client.post(
        f"/api/v1/invitations/{raw}/accept",
        data={"password": "whatever-123"},
        content_type="application/json",
    )
    assert r.status_code == 403
    # a different logged-in user is refused too
    r = client.post(
        f"/api/v1/invitations/{raw}/accept",
        data={},
        content_type="application/json",
        **hdr(people["collector"]["token"]),
    )
    assert r.status_code == 403
    token = token_for(client, "kofi@example.org")
    r = client.post(
        f"/api/v1/invitations/{raw}/accept", data={}, content_type="application/json", **hdr(token)
    )
    assert r.status_code == 200 and r.json()["access_token"] is None
    assert Membership.objects.get(user=existing, org=org).role == "manager"


def test_invite_by_phone_uses_sms(client, org_with_roles, capsys):
    org, people = org_with_roles
    r = invite(client, org, people["admin"]["token"], phone="+233 24 999 0000")
    assert r.status_code == 201 and r.json()["phone"] == "+233249990000"
    assert "[SMS] to +233249990000" in capsys.readouterr().out


def test_invite_validation_and_permissions(client, org_with_roles):
    org, people = org_with_roles
    assert invite(client, org, people["manager"]["token"], email="x@example.org").status_code == 403
    assert (
        invite(
            client, org, people["admin"]["token"], email="x@example.org", phone="+233240000000"
        ).status_code
        == 422
    )
    assert invite(client, org, people["admin"]["token"]).status_code == 422
    assert (
        invite(
            client, org, people["admin"]["token"], email="x@example.org", role="owner"
        ).status_code
        == 403
    )
    assert (
        invite(
            client, org, people["owner"]["token"], email="x@example.org", role="owner"
        ).status_code
        == 201
    )
    # already a member
    assert (
        invite(client, org, people["admin"]["token"], email="collector@example.org").status_code
        == 409
    )


def test_list_and_revoke_invitations(client, org_with_roles):
    org, people = org_with_roles
    inv_id = invite(client, org, people["admin"]["token"], email="a@example.org").json()["id"]
    r = client.get(f"/api/v1/orgs/{org.id}/invitations", **hdr(people["admin"]["token"], org))
    assert [i["id"] for i in r.json()] == [inv_id]
    raw = invitation_token_from_email()
    assert (
        client.delete(
            f"/api/v1/orgs/{org.id}/invitations/{inv_id}", **hdr(people["admin"]["token"], org)
        ).status_code
        == 204
    )
    assert client.get(f"/api/v1/invitations/{raw}").status_code == 404
    assert Invitation.objects.get(pk=inv_id).revoked_at is not None


def test_expired_or_bogus_invitation_is_404(client, org_with_roles):
    org, people = org_with_roles
    invite(client, org, people["admin"]["token"], email="a@example.org")
    raw = invitation_token_from_email()
    from datetime import timedelta

    from django.utils import timezone

    Invitation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.get(f"/api/v1/invitations/{raw}").status_code == 404
    assert client.get("/api/v1/invitations/not-a-token").status_code == 404


def test_invitations_are_scoped_to_their_org(client, org_with_roles):
    org, people = org_with_roles
    other = OrganisationFactory()
    other_admin = UserFactory(email="other@example.org")
    MembershipFactory(user=other_admin, org=other, role="admin")
    inv_id = invite(client, org, people["admin"]["token"], email="a@example.org").json()["id"]
    other_token = token_for(client, "other@example.org")
    assert (
        client.get(f"/api/v1/orgs/{other.id}/invitations", **hdr(other_token, other)).json() == []
    )
    assert (
        client.delete(
            f"/api/v1/orgs/{other.id}/invitations/{inv_id}", **hdr(other_token, other)
        ).status_code
        == 404
    )
