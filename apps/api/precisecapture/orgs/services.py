"""Organisation and membership business logic."""

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from precisecapture.accounts.messaging import is_email, sms_backend
from precisecapture.accounts.models import User, normalise_email, normalise_phone
from precisecapture.accounts.tokens import TokenPair, issue_pair
from precisecapture.common.errors import Conflict, Forbidden, NotFound, UnprocessableEntity
from precisecapture.common.permissions import can_assign_role
from precisecapture.orgs.models import Invitation, Membership, Organisation, Role

INVITATION_TTL_DAYS = 7


# --- organisations ----------------------------------------------------------------------


@transaction.atomic
def create_org(
    creator: User, *, name: str, country: str = "", org_settings: dict[str, Any] | None = None
) -> Membership:
    org = Organisation.objects.create(
        name=name,
        slug=Organisation.unique_slug(name),
        country=country.upper(),
        settings=org_settings or {},
    )
    return Membership.objects.create(user=creator, org=org, role=Role.OWNER)


def update_org(org: Organisation, data: dict[str, Any]) -> Organisation:
    if (
        "slug" in data
        and data["slug"]
        and Organisation.objects.exclude(pk=org.pk).filter(slug=data["slug"]).exists()
    ):
        raise Conflict("That slug is already taken.")
    for key, value in data.items():
        if value is not None:
            setattr(org, key, value.upper() if key == "country" else value)
    org.save()
    return org


# --- members ------------------------------------------------------------------------------


def _owners(org: Organisation) -> int:
    return Membership.objects.filter(org=org, role=Role.OWNER).count()


def change_role(actor: Membership, target_user_id: uuid.UUID, new_role: str) -> Membership:
    target = (
        Membership.objects.select_related("user")
        .filter(org=actor.org, user_id=target_user_id)
        .first()
    )
    if target is None:
        raise NotFound("Member not found")
    if not can_assign_role(actor.role, new_role) or not can_assign_role(actor.role, target.role):
        raise Forbidden("You cannot assign that role.")
    if target.role == Role.OWNER and new_role != Role.OWNER and _owners(actor.org) == 1:
        raise Conflict("An organisation must keep at least one owner.")
    target.role = new_role
    target.version += 1
    target.save(update_fields=["role", "version", "updated_at"])
    return target


def remove_member(actor: Membership, target_user_id: uuid.UUID) -> None:
    target = Membership.objects.filter(org=actor.org, user_id=target_user_id).first()
    if target is None:
        raise NotFound("Member not found")
    if target.pk != actor.pk and not can_assign_role(actor.role, target.role):
        raise Forbidden("You cannot remove a member with that role.")
    if target.role == Role.OWNER and _owners(actor.org) == 1:
        raise Conflict("An organisation must keep at least one owner.")
    target.delete()


# --- invitations --------------------------------------------------------------------------


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def invite(
    actor: Membership, *, email: str | None, phone: str | None, role: str
) -> tuple[Invitation, str]:
    email = normalise_email(email)
    phone = normalise_phone(phone)
    if bool(email) == bool(phone):
        raise UnprocessableEntity(
            "Give exactly one of email or phone",
            errors=[
                {"field": "email", "code": "one_of", "message": "Provide email or phone, not both"}
            ],
        )
    if not can_assign_role(actor.role, role):
        raise Forbidden("You cannot invite with that role.")
    existing = User.objects.by_identifier(email or phone or "")
    if existing is not None and Membership.objects.filter(org=actor.org, user=existing).exists():
        raise Conflict("That person is already a member.")

    raw = secrets.token_urlsafe(32)
    invitation = Invitation.objects.create(
        org=actor.org,
        email=email,
        phone=phone,
        role=role,
        token_hash=_hash(raw),
        invited_by=actor.user,
        expires_at=timezone.now() + timedelta(days=INVITATION_TTL_DAYS),
    )
    _send_invitation(invitation, raw)
    return invitation, raw


def _send_invitation(invitation: Invitation, raw: str) -> None:
    link = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/invitations/{raw}"
    body = (
        f"You have been invited to join {invitation.org.name} on {settings.INSTANCE_NAME} "
        f"as {invitation.role}. Open {link} to accept. "
        f"The link expires in {INVITATION_TTL_DAYS} days."
    )
    if invitation.email:
        send_mail(
            subject=f"Invitation to {invitation.org.name}",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.email],
        )
    elif invitation.phone:
        sms_backend().send(invitation.phone, body)


def revoke_invitation(actor: Membership, invitation_id: uuid.UUID) -> None:
    invitation = Invitation.objects.filter(org=actor.org, pk=invitation_id).first()
    if invitation is None:
        raise NotFound("Invitation not found")
    if invitation.accepted_at is not None:
        raise Conflict("Invitation already accepted")
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=["revoked_at", "updated_at"])


def invitation_by_token(raw: str) -> Invitation:
    invitation = Invitation.objects.select_related("org").filter(token_hash=_hash(raw)).first()
    if invitation is None or not invitation.is_open:
        raise NotFound("This invitation is invalid, expired or already used.")
    return invitation


def preview_invitation(raw: str) -> dict[str, Any]:
    inv = invitation_by_token(raw)
    return {
        "org_name": inv.org.name,
        "role": inv.role,
        "destination": inv.destination,
        "account_exists": User.objects.by_identifier(inv.destination) is not None,
        "expires_at": inv.expires_at,
    }


@transaction.atomic
def accept_invitation(
    raw: str, *, current_user: User | None, name: str | None, password: str | None
) -> tuple[Membership, TokenPair | None]:
    """
    Logged-in users accept as themselves when the invitation is addressed to one of their
    identifiers. Otherwise the destination must not belong to another account, and a new
    account is created from name + password (a token pair is returned so the client is
    logged in straight away).
    """
    inv = (
        Invitation.objects.select_for_update()
        .select_related("org")
        .get(pk=invitation_by_token(raw).pk)
    )
    addressee = User.objects.by_identifier(inv.destination)
    pair: TokenPair | None = None

    if current_user is not None:
        matches = addressee is not None and addressee.pk == current_user.pk
        if not matches:
            raise Forbidden("This invitation was sent to a different email or phone.")
        user = current_user
    elif addressee is not None:
        raise Forbidden(
            "An account already exists for this address. Log in, then accept the invitation."
        )
    else:
        if not password:
            raise UnprocessableEntity(
                "A password is required to create your account",
                errors=[{"field": "password", "code": "required", "message": "Set a password"}],
            )
        user = User.objects.create_user(
            email=inv.email, phone=inv.phone, password=password, name=name or ""
        )
        pair = issue_pair(user, None)

    if Membership.objects.filter(org=inv.org, user=user).exists():
        raise Conflict("You are already a member of this organisation.")
    membership = Membership.objects.create(
        user=user, org=inv.org, role=inv.role, invited_by=inv.invited_by
    )
    inv.accepted_at = timezone.now()
    inv.accepted_by = user
    inv.save(update_fields=["accepted_at", "accepted_by", "updated_at"])
    return membership, pair


__all__ = ["is_email"]
