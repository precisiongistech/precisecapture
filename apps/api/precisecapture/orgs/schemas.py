import uuid
from datetime import datetime
from typing import Any

from ninja import Field, Schema

from precisecapture.orgs.models import Role

ROLE_PATTERN = "^(owner|admin|manager|collector|viewer)$"


class OrgCreateIn(Schema):
    name: str = Field(..., min_length=2, max_length=160)
    country: str = Field("", max_length=2, description="ISO 3166-1 alpha-2")
    settings: dict[str, Any] = Field(default_factory=dict)


class OrgUpdateIn(Schema):
    name: str | None = Field(None, min_length=2, max_length=160)
    slug: str | None = Field(None, pattern="^[a-z0-9][a-z0-9-]{1,78}$")
    country: str | None = Field(None, max_length=2)
    settings: dict[str, Any] | None = None


class OrgOut(Schema):
    id: uuid.UUID
    name: str
    slug: str
    country: str
    plan: str
    settings: dict[str, Any]
    created_at: datetime


class OrgSummaryOut(Schema):
    id: uuid.UUID
    name: str
    slug: str
    role: str


class MemberOut(Schema):
    user_id: uuid.UUID
    email: str | None
    phone: str | None
    name: str
    role: str
    status: str
    joined_at: datetime


class MemberUpdateIn(Schema):
    role: str = Field(..., pattern=ROLE_PATTERN)


class InvitationIn(Schema):
    email: str | None = None
    phone: str | None = None
    role: str = Field(Role.COLLECTOR, pattern=ROLE_PATTERN)


class InvitationOut(Schema):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str | None
    phone: str | None
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None


class InvitationPreviewOut(Schema):
    org_name: str
    role: str
    destination: str
    account_exists: bool
    expires_at: datetime


class InvitationAcceptIn(Schema):
    name: str | None = Field(
        None, max_length=120, description="Required when creating a new account"
    )
    password: str | None = Field(
        None, min_length=8, description="Set for a new account (or use OTP later)"
    )


class InvitationAcceptOut(Schema):
    org_id: uuid.UUID
    role: str
    access_token: str | None
    refresh_token: str | None
    token_type: str = "Bearer"
    expires_in: int | None
