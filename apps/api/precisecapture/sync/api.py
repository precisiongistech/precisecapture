"""Sync endpoints (ENGINEERING_NOTES.md §2)."""

import gzip
import json
import uuid
from typing import Any

from django.http import HttpRequest
from ninja import Query, Router, Schema
from ninja.parser import Parser

from precisecapture.accounts.models import Device
from precisecapture.common.auth import (
    current_device_id,
    current_membership,
    current_user,
    tenant_auth,
)
from precisecapture.common.permissions import require_project_role
from precisecapture.projects import services as project_services
from precisecapture.sync import services
from precisecapture.sync.schemas import PullResponse, PushRequest, PushResponse

router = Router(tags=["sync"], auth=tenant_auth)


class GzipAwareParser(Parser):
    """Accept Content-Encoding: gzip on request bodies (low-bandwidth handling, SPEC.md §10)."""

    def parse_body(self, request: HttpRequest) -> Any:
        body = request.body
        if request.headers.get("Content-Encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
        return json.loads(body) if body else {}


def _device(request: HttpRequest) -> Device | None:
    device_id = current_device_id(request)
    return Device.objects.filter(pk=device_id).first() if device_id else None


def _project_for(request: HttpRequest, project_id: uuid.UUID, minimum: str) -> Any:
    project = project_services.get_project(project_id)
    require_project_role(
        current_membership(request),
        project_services.project_member_role(project, current_user(request)),
        minimum,
    )
    return project


@router.post("/push", response=PushResponse, operation_id="syncPush")
def push(request: HttpRequest, payload: PushRequest) -> dict[str, Any]:
    """
    Push up to 200 outbox changes for one project (gzip accepted). One transaction per project;
    per-change results are accepted | merged | conflict | rejected | duplicate. Idempotent on
    change_id: replaying a batch returns the stored results as `duplicate`.
    """
    project = _project_for(request, payload.project_id, "collector")
    changes = []
    for c in payload.changes:
        raw = c.model_dump(mode="json")
        raw["change_id"], raw["id"], raw["layer_id"] = c.change_id, c.id, c.layer_id
        changes.append(raw)
    outcome = services.push(project, current_user(request), _device(request), changes)
    return {
        "results": outcome.results,
        "last_seq": outcome.last_seq,
        "config_version": outcome.config_version,
    }


class PullParams(Schema):
    project: uuid.UUID
    cursor: int = 0
    limit: int = 500


@router.get("/pull", response=PullResponse, operation_id="syncPull")
def pull(request: HttpRequest, params: Query[PullParams]) -> dict[str, Any]:
    """
    Latest state of every feature changed since `cursor` (the last server_seq the device
    applied), in seq order, with `next_cursor`, `has_more` and the project's `config_version`.
    Review status changes and send-back notes are included. `limit` is 1-500.
    """
    project = _project_for(request, params.project, "viewer")
    limit = max(1, min(params.limit, 500))
    return services.pull(project, _device(request), max(0, params.cursor), limit)
