import uuid
from typing import Any

from django.http import HttpRequest
from ninja import Router
from ninja.responses import Status

from precisecapture.accounts import services, tokens
from precisecapture.accounts.models import Device
from precisecapture.accounts.schemas import (
    DeviceIn,
    DeviceOut,
    LoginIn,
    LogoutIn,
    MeOut,
    RefreshIn,
    TokenPairOut,
)
from precisecapture.common.auth import current_device_id, current_user, user_auth
from precisecapture.common.errors import NotFound

auth_router = Router(tags=["auth"])
me_router = Router(tags=["me"])
devices_router = Router(tags=["devices"])


@auth_router.post("/login", response=TokenPairOut, auth=None, operation_id="login")
def login(request: HttpRequest, payload: LoginIn) -> tokens.TokenPair:
    """Password login with an email or phone identifier.

    Returns a 15 minute access JWT and a 30 day rotating refresh token.
    """
    return services.login(request, payload.identifier, payload.password, payload.device_id)


@auth_router.post("/refresh", response=TokenPairOut, auth=None, operation_id="refresh")
def refresh(request: HttpRequest, payload: RefreshIn) -> tokens.TokenPair:
    """Rotate a refresh token. Reusing an already rotated token revokes the whole chain."""
    return tokens.rotate(payload.refresh_token)


@auth_router.post("/logout", response={204: None}, auth=None, operation_id="logout")
def logout(request: HttpRequest, payload: LogoutIn) -> Status[None]:
    """Revoke the refresh token chain. Idempotent."""
    tokens.revoke(payload.refresh_token)
    return Status(204, None)


@me_router.get("", response=MeOut, auth=user_auth, operation_id="me")
def me(request: HttpRequest) -> dict[str, Any]:
    """The current user and every organisation they belong to."""
    return services.me(current_user(request), current_device_id(request))


@me_router.get(
    "/projects", response=list[dict[str, Any]], auth=user_auth, operation_id="myProjects"
)
def my_projects(request: HttpRequest) -> list[dict[str, Any]]:
    """Projects the user is assigned to across all their organisations (filled in M3)."""
    return []


@devices_router.post("", response={201: DeviceOut}, auth=user_auth, operation_id="registerDevice")
def register_device(request: HttpRequest, payload: DeviceIn) -> Status[Device]:
    """Register (or update) this device. Send the client-generated UUIDv7 as `id`."""
    return Status(201, services.register_device(current_user(request), payload.dict()))


@devices_router.get("", response=list[DeviceOut], auth=user_auth, operation_id="listDevices")
def list_devices(request: HttpRequest) -> Any:
    return Device.objects.filter(user=current_user(request)).order_by("-last_seen_at")


@devices_router.delete(
    "/{device_id}", response={204: None}, auth=user_auth, operation_id="revokeDevice"
)
def revoke_device(request: HttpRequest, device_id: uuid.UUID) -> Status[None]:
    """Revoke a lost device: its refresh tokens stop working immediately."""
    device = Device.objects.filter(pk=device_id, user=current_user(request)).first()
    if device is None:
        raise NotFound("Device not found")
    tokens.revoke_device(device)
    return Status(204, None)
