"""Account business logic: login, devices, profile."""

import uuid
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.http import HttpRequest
from django.utils import timezone

from precisecapture.accounts.models import Device, User
from precisecapture.accounts.tokens import TokenPair, issue_pair
from precisecapture.common import ratelimit
from precisecapture.common.errors import NotFound, Unauthorized
from precisecapture.orgs.models import Membership

# A hash to compare against when the user does not exist, so timing does not reveal accounts.
_DUMMY_HASH = "argon2$argon2id$v=19$m=102400,t=2,p=8$c29tZXNhbHQ$Zm9vYmFy"


def client_ip(request: HttpRequest) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return str(forwarded).split(",")[0].strip()
    return str(request.META.get("REMOTE_ADDR", ""))


def login(
    request: HttpRequest, identifier: str, password: str, device_id: uuid.UUID | None
) -> TokenPair:
    ident = identifier.strip().lower()
    ratelimit.hit("login:id", ident, settings.RATE_LIMIT_LOGIN_PER_IDENTIFIER)
    ratelimit.hit("login:ip", client_ip(request), settings.RATE_LIMIT_LOGIN_PER_IP)

    user = User.objects.by_identifier(identifier)
    if user is None or not user.has_usable_password():
        check_password(password, _DUMMY_HASH)
        raise Unauthorized("Invalid credentials")
    if not user.check_password(password):
        raise Unauthorized("Invalid credentials")
    if not user.is_active:
        raise Unauthorized("Account disabled")

    device = _device_for(user, device_id)
    user.mark_login()
    ratelimit.reset("login:id", ident)
    return issue_pair(user, device)


def _device_for(user: User, device_id: uuid.UUID | None) -> Device | None:
    if device_id is None:
        return None
    device = Device.objects.filter(pk=device_id, user=user, revoked_at__isnull=True).first()
    if device is None:
        raise Unauthorized("Unknown or revoked device; register it with POST /devices first")
    device.last_seen_at = timezone.now()
    device.save(update_fields=["last_seen_at", "updated_at"])
    return device


def register_device(user: User, data: dict[str, Any]) -> Device:
    """Idempotent on the client-generated id: re-registering updates the metadata."""
    device_id = data.pop("id", None)
    if device_id is not None:
        existing = Device.objects.filter(pk=device_id).first()
        if existing is not None:
            if existing.user_id != user.id:
                raise NotFound("Device not found")
            for key, value in data.items():
                setattr(existing, key, value)
            existing.last_seen_at = timezone.now()
            existing.revoked_at = None
            existing.save()
            return existing
    return Device.objects.create(
        user=user, last_seen_at=timezone.now(), **({"id": device_id} if device_id else {}), **data
    )


def me(user: User, device_id: uuid.UUID | None) -> dict[str, Any]:
    memberships = Membership.objects.select_related("org").filter(user=user).order_by("org__name")
    return {
        "user": user,
        "memberships": [
            {
                "org_id": m.org_id,
                "org_name": m.org.name,
                "org_slug": m.org.slug,
                "role": m.role,
                "version": m.version,
            }
            for m in memberships
        ],
        "device_id": device_id,
    }
