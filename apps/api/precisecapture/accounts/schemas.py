import uuid
from datetime import datetime

from ninja import Field, Schema


class LoginIn(Schema):
    identifier: str = Field(
        ..., description="Email address or E.164 phone number", examples=["ama@example.org"]
    )
    password: str = Field(..., min_length=1)
    device_id: uuid.UUID | None = Field(None, description="A device registered with POST /devices")


class RefreshIn(Schema):
    refresh_token: str


class LogoutIn(Schema):
    refresh_token: str


class TokenPairOut(Schema):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(..., description="Access token lifetime in seconds")


class MembershipOut(Schema):
    org_id: uuid.UUID
    org_name: str
    org_slug: str
    role: str
    version: int


class UserOut(Schema):
    id: uuid.UUID
    email: str | None
    phone: str | None
    name: str
    status: str


class MeOut(Schema):
    user: UserOut
    memberships: list[MembershipOut]
    device_id: uuid.UUID | None


class DeviceIn(Schema):
    id: uuid.UUID | None = Field(None, description="Client-generated UUIDv7; the server keeps it")
    platform: str = Field(..., pattern="^(android|ios|web)$")
    model: str = ""
    os_version: str = ""
    app_version: str = ""
    push_token: str = ""


class DeviceOut(Schema):
    id: uuid.UUID
    platform: str
    model: str
    os_version: str
    app_version: str
    last_seen_at: datetime | None
    last_sync_at: datetime | None
    revoked_at: datetime | None


class OtpRequestIn(Schema):
    destination: str = Field(..., description="Email address or E.164 phone number")


class OtpRequestOut(Schema):
    detail: str = "If an account exists for this destination, a code has been sent."
    expires_in: int = Field(..., description="Code lifetime in seconds")


class OtpVerifyIn(Schema):
    destination: str
    code: str = Field(..., min_length=4, max_length=8)
    device_id: uuid.UUID | None = None
