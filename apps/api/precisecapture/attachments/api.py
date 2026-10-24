"""Attachment endpoints (ENGINEERING_NOTES.md §5)."""

import uuid
from typing import Any

from django.http import HttpRequest
from ninja import Router
from ninja.responses import Status

from precisecapture.accounts.models import Device
from precisecapture.attachments import services
from precisecapture.attachments.models import Attachment
from precisecapture.attachments.schemas import (
    AttachmentCompleteIn,
    AttachmentCreateIn,
    AttachmentOut,
    AttachmentUploadOut,
    MissingAttachmentsOut,
)
from precisecapture.common.auth import (
    current_device_id,
    current_membership,
    current_user,
    tenant_auth,
)
from precisecapture.common.permissions import require_project_role
from precisecapture.features import services as feature_services
from precisecapture.projects import services as project_services

router = Router(tags=["attachments"], auth=tenant_auth)
feature_attachments_router = Router(tags=["attachments"], auth=tenant_auth)
reports_router = Router(tags=["attachments"], auth=tenant_auth)


def _device(request: HttpRequest) -> Device | None:
    device_id = current_device_id(request)
    return Device.objects.filter(pk=device_id).first() if device_id else None


def _require(request: HttpRequest, project: Any, minimum: str) -> None:
    require_project_role(
        current_membership(request),
        project_services.project_member_role(project, current_user(request)),
        minimum,
    )


@router.post("", response={201: AttachmentUploadOut}, operation_id="createAttachment")
def create_attachment(request: HttpRequest, payload: AttachmentCreateIn) -> Status[dict[str, Any]]:
    """
    Start a resumable upload: returns an S3 multipart upload id and presigned part URLs (8 MB
    parts, valid 1 h). Upload the parts directly to storage, then call complete. Re-posting the
    same id continues an unfinished upload.
    """
    feature = feature_services.get_feature(payload.feature_id)
    _require(request, feature.project, "collector")
    att, missing = services.create_upload(
        feature, current_user(request), _device(request), payload.dict()
    )
    return Status(201, services.upload_response(att, missing))


@router.get(
    "/{attachment_id}/upload", response=AttachmentUploadOut, operation_id="resumeAttachmentUpload"
)
def resume_upload(request: HttpRequest, attachment_id: uuid.UUID) -> dict[str, Any]:
    """Resume: fresh presigned URLs for the parts storage does not have yet."""
    att = services.get_attachment(attachment_id)
    _require(request, att.project, "collector")
    att, missing = services.resume_upload(att)
    return services.upload_response(att, missing)


@router.post("/{attachment_id}/complete", response=AttachmentOut, operation_id="completeAttachment")
def complete_attachment(
    request: HttpRequest, attachment_id: uuid.UUID, payload: AttachmentCompleteIn
) -> dict[str, Any]:
    """Finish the multipart upload; size and SHA-256 verified (422, object removed on mismatch)."""
    att = services.get_attachment(attachment_id)
    _require(request, att.project, "collector")
    return services.attachment_out(services.complete_upload(att, [p.dict() for p in payload.parts]))


@router.get("/{attachment_id}", response=AttachmentOut, operation_id="getAttachment")
def get_attachment(request: HttpRequest, attachment_id: uuid.UUID) -> dict[str, Any]:
    """Metadata plus a 15-minute presigned download URL (and thumbnail URL for images)."""
    att = services.get_attachment(attachment_id)
    _require(request, att.project, "viewer")
    return services.attachment_out(att)


@feature_attachments_router.get(
    "/{feature_id}/attachments", response=list[AttachmentOut], operation_id="listFeatureAttachments"
)
def list_feature_attachments(request: HttpRequest, feature_id: uuid.UUID) -> list[dict[str, Any]]:
    feature = feature_services.get_feature(feature_id)
    _require(request, feature.project, "viewer")
    return [
        services.attachment_out(a)
        for a in Attachment.objects.filter(feature=feature).order_by("created_at")
    ]


@reports_router.get(
    "/{project_id}/reports/missing-attachments",
    response=list[MissingAttachmentsOut],
    operation_id="missingAttachmentsReport",
)
def missing_attachments(request: HttpRequest, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """Features whose required photo/file fields have no completed upload."""
    project = project_services.get_project(project_id)
    _require(request, project, "manager")
    return services.missing_attachments(project)
