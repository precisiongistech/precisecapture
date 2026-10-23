import uuid
from datetime import datetime
from typing import Any

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema

from precisecapture.common.auth import current_membership, current_user, tenant_auth
from precisecapture.common.permissions import require_project_role
from precisecapture.projects import services as project_services
from precisecapture.sync import services
from precisecapture.sync.models import Conflict

router = Router(tags=["conflicts"], auth=tenant_auth)


class ConflictOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    feature_id: uuid.UUID
    layer_id: uuid.UUID
    reason: str
    base_version: int | None
    server_version: int
    overlapping_fields: list[str]
    local_payload: dict[str, Any]
    server_payload: dict[str, Any]
    status: str
    resolution: str
    device_id: uuid.UUID | None
    user_id: uuid.UUID | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    created_at: datetime


class ConflictListParams(Schema):
    project: uuid.UUID | None = None
    status: str = Field("open", pattern="^(open|resolved|all)$")


class ResolveIn(Schema):
    resolution: str = Field(..., pattern="^(keep_server|keep_device|merged)$")
    merged: dict[str, Any] | None = Field(
        None, description="{geom, attributes, status} when resolution=merged"
    )


def _out(c: Conflict) -> dict[str, Any]:
    return {
        "id": c.id,
        "project_id": c.project_id,
        "feature_id": c.feature_id,
        "layer_id": c.feature.layer_id,
        "reason": c.reason,
        "base_version": c.base_version,
        "server_version": c.server_version,
        "overlapping_fields": c.overlapping_fields,
        "local_payload": c.local_payload,
        "server_payload": c.server_payload,
        "status": c.status,
        "resolution": c.resolution,
        "device_id": c.device_id,
        "user_id": c.user_id,
        "resolved_by": c.resolved_by_id,
        "resolved_at": c.resolved_at,
        "created_at": c.created_at,
    }


def _check(request: HttpRequest, conflict: Conflict, minimum: str) -> None:
    require_project_role(
        current_membership(request),
        project_services.project_member_role(conflict.project, current_user(request)),
        minimum,
    )


@router.get("", response=list[ConflictOut], operation_id="listConflicts")
def list_conflicts(request: HttpRequest, params: Query[ConflictListParams]) -> list[dict[str, Any]]:
    """Open (default), resolved or all conflicts in the projects the caller manages."""
    qs = Conflict.objects.select_related("feature", "project").order_by("-created_at")
    membership = current_membership(request)
    if params.project:
        project = project_services.get_project(params.project)
        require_project_role(
            membership,
            project_services.project_member_role(project, current_user(request)),
            "manager",
        )
        qs = qs.filter(project=project)
    else:
        from precisecapture.projects.services import visible_projects

        qs = qs.filter(project__in=[p.id for p in visible_projects(membership)])
    if params.status != "all":
        qs = qs.filter(status=params.status)
    return [_out(c) for c in qs[:500]]


@router.get("/{conflict_id}", response=ConflictOut, operation_id="getConflict")
def get_conflict(request: HttpRequest, conflict_id: uuid.UUID) -> dict[str, Any]:
    conflict = services.get_conflict(conflict_id)
    _check(request, conflict, "manager")
    return _out(conflict)


@router.post("/{conflict_id}/resolve", response=ConflictOut, operation_id="resolveConflict")
def resolve(request: HttpRequest, conflict_id: uuid.UUID, payload: ResolveIn) -> dict[str, Any]:
    """Keep the server state, apply the device's payload, or write a merged one. Managers only."""
    conflict = services.get_conflict(conflict_id)
    _check(request, conflict, "manager")
    services.resolve_conflict(conflict, current_user(request), payload.resolution, payload.merged)
    return _out(services.get_conflict(conflict.id))
