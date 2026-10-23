"""Attachment endpoints: typed stubs (501) in M4, implemented in M7."""

import uuid

from django.http import HttpRequest
from ninja import Router

from precisecapture.attachments.schemas import (
    AttachmentCompleteIn,
    AttachmentCreateIn,
    AttachmentOut,
    AttachmentUploadOut,
)
from precisecapture.common.auth import tenant_auth
from precisecapture.common.errors import NotImplementedYet

router = Router(tags=["attachments"], auth=tenant_auth)


@router.post(
    "",
    response={201: AttachmentUploadOut},
    operation_id="createAttachment",
)
def create_attachment(request: HttpRequest, payload: AttachmentCreateIn) -> AttachmentUploadOut:
    """
    Start a resumable upload: returns an S3 multipart upload id and presigned part URLs (8 MB
    parts). The client uploads parts directly to storage. **Returns 501 until M7.**
    """
    raise NotImplementedYet("Attachments land in milestone M7")


@router.post("/{attachment_id}/complete", response=AttachmentOut, operation_id="completeAttachment")
def complete_attachment(
    request: HttpRequest, attachment_id: uuid.UUID, payload: AttachmentCompleteIn
) -> AttachmentOut:
    """Finish the multipart upload with the part ETags; size and checksum verified. 501 until M7."""
    raise NotImplementedYet("Attachments land in milestone M7")


@router.get("/{attachment_id}", response=AttachmentOut, operation_id="getAttachment")
def get_attachment(request: HttpRequest, attachment_id: uuid.UUID) -> AttachmentOut:
    """Attachment metadata with a short-lived presigned download URL. **501 until M7.**"""
    raise NotImplementedYet("Attachments land in milestone M7")
