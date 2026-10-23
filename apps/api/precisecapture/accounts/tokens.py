"""
Access and refresh tokens (ENGINEERING_NOTES.md §6).

- Access: JWT, HS256 with JWT_SIGNING_KEY, 15 min. Claims: sub (user id), dev (device id or
  null), iat, exp, jti. Stateless; revocation happens at the refresh token level.
- Refresh: 32 random bytes, base64url; only the SHA-256 is stored. Rotated on use; reuse
  revokes the family. Bound to a device when the client registered one.
"""

import base64
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from precisecapture.accounts.models import Device, RefreshToken, User
from precisecapture.common.errors import Unauthorized
from precisecapture.common.ids import uuid7

ALGORITHM = "HS256"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_access_token(user: User, device: Device | None) -> str:
    now = timezone.now()
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "dev": str(device.id) if device else None,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.JWT_ACCESS_TTL_SECONDS)).timestamp()),
        "jti": str(uuid7()),
    }
    return jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=ALGORITHM)


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    device_id: uuid.UUID | None


def verify_access_token(token: str) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SIGNING_KEY,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
        dev = payload.get("dev")
        return AccessClaims(
            user_id=uuid.UUID(str(payload["sub"])), device_id=uuid.UUID(str(dev)) if dev else None
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise Unauthorized("Invalid or expired access token") from exc


def _new_refresh(user: User, device: Device | None, family: uuid.UUID) -> tuple[str, RefreshToken]:
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    row = RefreshToken.objects.create(
        user=user,
        device=device,
        token_hash=_hash(raw),
        family=family,
        expires_at=timezone.now() + timedelta(days=settings.JWT_REFRESH_TTL_DAYS),
    )
    return raw, row


def issue_pair(user: User, device: Device | None) -> TokenPair:
    raw, _ = _new_refresh(user, device, family=uuid7())
    return TokenPair(
        access_token=issue_access_token(user, device),
        refresh_token=raw,
        expires_in=settings.JWT_ACCESS_TTL_SECONDS,
    )


def _revoke_family(family: uuid.UUID) -> None:
    RefreshToken.objects.filter(family=family, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def rotate(raw_refresh: str) -> TokenPair:
    """Exchange a refresh token for a new pair. Reuse of a rotated token revokes the family."""
    replayed_family: uuid.UUID | None = None
    with transaction.atomic():
        row = (
            RefreshToken.objects.select_for_update(of=("self",))
            .select_related("user", "device")
            .filter(token_hash=_hash(raw_refresh))
            .first()
        )
        if row is None:
            raise Unauthorized("Unknown refresh token")
        if row.replaced_by_id is not None:
            # Token theft or a very confused client: cut the whole chain. The revocation must
            # survive the error, so it is done outside this savepoint (below).
            replayed_family = row.family
        elif row.revoked_at is not None or row.expires_at <= timezone.now():
            raise Unauthorized("Refresh token revoked or expired")
        elif not row.user.is_active:
            raise Unauthorized("Account disabled")
        elif row.device is not None and row.device.revoked_at is not None:
            raise Unauthorized("Device revoked")
        else:
            raw, new_row = _new_refresh(row.user, row.device, row.family)
            row.replaced_by = new_row
            row.last_used_at = timezone.now()
            row.save(update_fields=["replaced_by", "last_used_at", "updated_at"])
            return TokenPair(
                access_token=issue_access_token(row.user, row.device),
                refresh_token=raw,
                expires_in=settings.JWT_ACCESS_TTL_SECONDS,
            )
    _revoke_family(replayed_family)
    raise Unauthorized("Refresh token was already used; all sessions in this chain are revoked")


def revoke(raw_refresh: str) -> None:
    """Logout: revoke this token's whole family. Unknown tokens are ignored (idempotent)."""
    row = RefreshToken.objects.filter(token_hash=_hash(raw_refresh)).first()
    if row is not None:
        _revoke_family(row.family)


def revoke_device(device: Device) -> None:
    now = timezone.now()
    device.revoked_at = now
    device.save(update_fields=["revoked_at", "updated_at"])
    RefreshToken.objects.filter(device=device, revoked_at__isnull=True).update(revoked_at=now)
