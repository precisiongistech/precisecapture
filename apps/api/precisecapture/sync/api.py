"""Sync endpoints: typed stubs (501) in M4, implemented in M6 (ENGINEERING_NOTES.md §2)."""

import uuid

from django.http import HttpRequest
from ninja import Query, Router, Schema

from precisecapture.common.auth import tenant_auth
from precisecapture.common.errors import NotImplementedYet
from precisecapture.sync.schemas import (
    PullResponse,
    PushRequest,
    PushResponse,
)

router = Router(tags=["sync"], auth=tenant_auth)


@router.post(
    "/push",
    response=PushResponse,
    operation_id="syncPush",
)
def push(request: HttpRequest, payload: PushRequest) -> PushResponse:
    """
    Push up to 200 outbox changes for one project (gzip accepted). One transaction per project;
    per-change results are accepted | merged | conflict | rejected | duplicate. Idempotent on
    change_id. **Not implemented until M6: returns 501.**
    """
    raise NotImplementedYet("Sync push lands in milestone M6")


class PullParams(Schema):
    project: uuid.UUID
    cursor: int = 0
    limit: int = 500


@router.get("/pull", response=PullResponse, operation_id="syncPull")
def pull(request: HttpRequest, params: Query[PullParams]) -> PullResponse:
    """
    Latest state of every feature changed since `cursor` (the last server_seq the device
    applied), in seq order, with `next_cursor`, `has_more` and the project's `config_version`.
    `limit` is 1-500. **Not implemented until M6: returns 501.**
    """
    raise NotImplementedYet("Sync pull lands in milestone M6")
