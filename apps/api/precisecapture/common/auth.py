"""
Django Ninja authentication (ENGINEERING_NOTES.md §1 and §6).

- `UserAuth`: a valid access JWT. For endpoints that span organisations (/me, /auth/logout,
  /devices, /orgs creation). Sets request.user and request.device_id. No tenant is set.
- `TenantAuth`: UserAuth plus the `X-Org-Id` header. Verifies the membership, then sets the
  tenant for the request transaction with set_config. 403 when the user is not a member.

Both run inside the Ninja view, i.e. inside ATOMIC_REQUESTS, which is why the tenant is not
set in middleware.
"""

import uuid
from typing import Any

from django.http import HttpRequest
from ninja.security import HttpBearer

from precisecapture.accounts.models import User
from precisecapture.accounts.tokens import verify_access_token
from precisecapture.common.errors import Forbidden, ProblemException, Unauthorized
from precisecapture.common.tenancy import enter_tenant
from precisecapture.orgs.models import Membership, Organisation

ORG_HEADER = "X-Org-Id"


class MissingOrgHeader(ProblemException):
    status = 400
    slug = "missing-org-header"
    title = "Missing X-Org-Id header"


class UserAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str) -> Any:
        claims = verify_access_token(token)
        user = User.objects.filter(pk=claims.user_id).first()
        if user is None or not user.is_active:
            raise Unauthorized("Account not found or disabled")
        request.user = user
        request.device_id = claims.device_id  # type: ignore[attr-defined]
        return user


class TenantAuth(UserAuth):
    def authenticate(self, request: HttpRequest, token: str) -> Any:
        user: User = super().authenticate(request, token)
        raw = request.headers.get(ORG_HEADER)
        if not raw:
            raise MissingOrgHeader(f"Tenant endpoints require the {ORG_HEADER} header.")
        try:
            org_id = uuid.UUID(raw)
        except ValueError as exc:
            raise MissingOrgHeader(f"{ORG_HEADER} must be a UUID.") from exc
        membership = (
            Membership.objects.select_related("org").filter(user=user, org_id=org_id).first()
        )
        if membership is None:
            raise Forbidden("You are not a member of this organisation.")
        enter_tenant(org_id)
        request.org = membership.org  # type: ignore[attr-defined]
        request.membership = membership  # type: ignore[attr-defined]
        return user


user_auth = UserAuth()
tenant_auth = TenantAuth()


def current_org(request: HttpRequest) -> Organisation:
    org: Organisation = request.org  # type: ignore[attr-defined]
    return org


def current_membership(request: HttpRequest) -> Membership:
    membership: Membership = request.membership  # type: ignore[attr-defined]
    return membership


def current_user(request: HttpRequest) -> User:
    user = request.user
    assert isinstance(user, User)  # guaranteed by UserAuth
    return user


def current_device_id(request: HttpRequest) -> uuid.UUID | None:
    device_id: uuid.UUID | None = getattr(request, "device_id", None)
    return device_id
