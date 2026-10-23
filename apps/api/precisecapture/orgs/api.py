import uuid
from typing import Any

from django.http import HttpRequest
from ninja import Router
from ninja.responses import Status

from precisecapture.accounts.tokens import verify_access_token
from precisecapture.common.auth import (
    current_membership,
    current_org,
    current_user,
    tenant_auth,
    user_auth,
)
from precisecapture.common.errors import Forbidden
from precisecapture.common.permissions import require_role
from precisecapture.orgs import services
from precisecapture.orgs.models import Invitation, Membership, Role
from precisecapture.orgs.schemas import (
    InvitationAcceptIn,
    InvitationAcceptOut,
    InvitationIn,
    InvitationOut,
    InvitationPreviewOut,
    MemberOut,
    MemberUpdateIn,
    OrgCreateIn,
    OrgOut,
    OrgUpdateIn,
)

orgs_router = Router(tags=["orgs"])
invitations_router = Router(tags=["orgs"])


@orgs_router.post("", response={201: OrgOut}, auth=user_auth, operation_id="createOrg")
def create_org(request: HttpRequest, payload: OrgCreateIn) -> Status[Any]:
    """Create an organisation. The creator becomes its owner."""
    membership = services.create_org(
        current_user(request),
        name=payload.name,
        country=payload.country,
        org_settings=payload.settings,
    )
    return Status(201, membership.org)


# Everything below is tenant-scoped: X-Org-Id must name the org in the path.


def _own_org(request: HttpRequest, org_id: uuid.UUID) -> None:
    if current_org(request).id != org_id:
        raise Forbidden("X-Org-Id does not match the organisation in the path.")


@orgs_router.get("/{org_id}", response=OrgOut, auth=tenant_auth, operation_id="getOrg")
def get_org(request: HttpRequest, org_id: uuid.UUID) -> Any:
    _own_org(request, org_id)
    return current_org(request)


@orgs_router.patch("/{org_id}", response=OrgOut, auth=tenant_auth, operation_id="updateOrg")
def update_org(request: HttpRequest, org_id: uuid.UUID, payload: OrgUpdateIn) -> Any:
    """Owners and admins may change name, slug, country and settings (incl. capture defaults)."""
    _own_org(request, org_id)
    require_role(request, Role.ADMIN)
    return services.update_org(current_org(request), payload.dict(exclude_unset=True))


def _member_out(m: Membership) -> dict[str, Any]:
    return {
        "user_id": m.user_id,
        "email": m.user.email,
        "phone": m.user.phone,
        "name": m.user.name,
        "role": m.role,
        "status": m.user.status,
        "joined_at": m.created_at,
    }


@orgs_router.get(
    "/{org_id}/members", response=list[MemberOut], auth=tenant_auth, operation_id="listMembers"
)
def list_members(request: HttpRequest, org_id: uuid.UUID) -> list[dict[str, Any]]:
    _own_org(request, org_id)
    require_role(request, Role.MANAGER)
    rows = (
        Membership.objects.select_related("user")
        .filter(org=current_org(request))
        .order_by("user__name")
    )
    return [_member_out(m) for m in rows]


@orgs_router.patch(
    "/{org_id}/members/{user_id}",
    response=MemberOut,
    auth=tenant_auth,
    operation_id="updateMemberRole",
)
def update_member(
    request: HttpRequest, org_id: uuid.UUID, user_id: uuid.UUID, payload: MemberUpdateIn
) -> dict[str, Any]:
    _own_org(request, org_id)
    actor = require_role(request, Role.ADMIN)
    return _member_out(services.change_role(actor, user_id, payload.role))


@orgs_router.delete(
    "/{org_id}/members/{user_id}",
    response={204: None},
    auth=tenant_auth,
    operation_id="removeMember",
)
def remove_member(request: HttpRequest, org_id: uuid.UUID, user_id: uuid.UUID) -> Status[None]:
    """Admins remove members; any member may remove themselves (except the last owner)."""
    _own_org(request, org_id)
    actor = current_membership(request)
    if actor.user_id != user_id:
        require_role(request, Role.ADMIN)
    services.remove_member(actor, user_id)
    return Status(204, None)


@orgs_router.post(
    "/{org_id}/invitations",
    response={201: InvitationOut},
    auth=tenant_auth,
    operation_id="inviteMember",
)
def invite(request: HttpRequest, org_id: uuid.UUID, payload: InvitationIn) -> Status[Invitation]:
    """Invite by email or phone. The token travels only in the message, never in this response."""
    _own_org(request, org_id)
    actor = require_role(request, Role.ADMIN)
    invitation, _raw = services.invite(
        actor, email=payload.email, phone=payload.phone, role=payload.role
    )
    return Status(201, invitation)


@orgs_router.get(
    "/{org_id}/invitations",
    response=list[InvitationOut],
    auth=tenant_auth,
    operation_id="listInvitations",
)
def list_invitations(request: HttpRequest, org_id: uuid.UUID) -> Any:
    _own_org(request, org_id)
    require_role(request, Role.ADMIN)
    return Invitation.objects.filter(org=current_org(request), accepted_at__isnull=True).order_by(
        "-created_at"
    )


@orgs_router.delete(
    "/{org_id}/invitations/{invitation_id}",
    response={204: None},
    auth=tenant_auth,
    operation_id="revokeInvitation",
)
def revoke_invitation(
    request: HttpRequest, org_id: uuid.UUID, invitation_id: uuid.UUID
) -> Status[None]:
    _own_org(request, org_id)
    actor = require_role(request, Role.ADMIN)
    services.revoke_invitation(actor, invitation_id)
    return Status(204, None)


# Invitation acceptance happens before a tenant is known: token in the path, optional bearer.


@invitations_router.get(
    "/{token}", response=InvitationPreviewOut, auth=None, operation_id="previewInvitation"
)
def preview_invitation(request: HttpRequest, token: str) -> dict[str, Any]:
    """What the invitee sees before accepting: org, role, whether an account must be created."""
    return services.preview_invitation(token)


@invitations_router.post(
    "/{token}/accept", response=InvitationAcceptOut, auth=None, operation_id="acceptInvitation"
)
def accept_invitation(
    request: HttpRequest, token: str, payload: InvitationAcceptIn
) -> dict[str, Any]:
    """Accept as the logged-in user (bearer token) or create an account (name + password)."""
    user = None
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        claims = verify_access_token(header.removeprefix("Bearer ").strip())
        from precisecapture.accounts.models import User

        user = User.objects.filter(pk=claims.user_id, status=User.Status.ACTIVE).first()
    membership, pair = services.accept_invitation(
        token, current_user=user, name=payload.name, password=payload.password
    )
    return {
        "org_id": membership.org_id,
        "role": membership.role,
        "access_token": pair.access_token if pair else None,
        "refresh_token": pair.refresh_token if pair else None,
        "expires_in": pair.expires_in if pair else None,
    }
