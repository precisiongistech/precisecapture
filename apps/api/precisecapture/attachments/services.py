"""Resumable attachment uploads (ENGINEERING_NOTES.md §5)."""

import mimetypes
import uuid
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from precisecapture.accounts.models import Device, User
from precisecapture.attachments import storage
from precisecapture.attachments.models import Attachment, UploadStatus
from precisecapture.common.errors import Conflict, NotFound, UnprocessableEntity
from precisecapture.features.models import Feature
from precisecapture.projects.models import Project
from precisecapture.projects.schema_services import current_schema

MEDIA_TYPES = {"photo", "audio", "video", "file", "signature"}
MAX_SIZE = 500 * 1024 * 1024
UPLOAD_TTL_DAYS = 7


def _media_fields(feature: Feature) -> dict[str, dict[str, Any]]:
    schema = current_schema(feature.layer)
    out: dict[str, dict[str, Any]] = {}
    if schema is None:
        return out

    def walk(fields: list[dict[str, Any]]) -> None:
        for f in fields:
            if f.get("type") in MEDIA_TYPES:
                out[f["key"]] = f
            if f.get("type") in ("group", "repeat"):
                walk(f.get("fields") or [])

    walk(schema.attributes.get("fields") or [])
    return out


def _extension(content_type: str) -> str:
    ext = mimetypes.guess_extension(content_type) or ""
    return {".jpe": ".jpg", ".jpeg": ".jpg"}.get(ext, ext)


def storage_key(feature: Feature, attachment_id: uuid.UUID, content_type: str) -> str:
    return (
        f"org/{feature.org_id}/project/{feature.project_id}/feature/{feature.id}/"
        f"{attachment_id}{_extension(content_type)}"
    )


def _presigned_parts(att: Attachment, numbers: list[int]) -> list[dict[str, Any]]:
    return [
        {"part_number": n, "url": storage.presign_part(att.storage_key, att.upload_id, n)}
        for n in numbers
    ]


def upload_response(att: Attachment, missing: list[int]) -> dict[str, Any]:
    return {
        "id": att.id,
        "upload_id": att.upload_id,
        "part_size": att.part_size,
        "parts": _presigned_parts(att, missing),
        "expires_at": timezone.now() + timedelta(seconds=storage.PART_URL_TTL_SECONDS),
    }


def get_attachment(attachment_id: uuid.UUID) -> Attachment:
    att = (
        Attachment.objects.select_related("feature", "feature__layer", "project")
        .filter(pk=attachment_id)
        .first()
    )
    if att is None:
        raise NotFound("Attachment not found")
    return att


@transaction.atomic
def create_upload(
    feature: Feature, user: User, device: Device | None, data: dict[str, Any]
) -> tuple[Attachment, list[int]]:
    existing = Attachment.objects.filter(pk=data["id"]).first()
    if existing is not None:
        if existing.upload_status == UploadStatus.COMPLETE:
            raise Conflict("This attachment is already uploaded")
        if existing.feature_id != feature.id:
            raise Conflict("Attachment id already used")
        return resume_upload(existing)
    fields = _media_fields(feature)
    if data["field_key"] not in fields:
        raise UnprocessableEntity(
            "Not a media field of this layer",
            errors=[
                {
                    "field": "field_key",
                    "code": "not_media",
                    "message": f"'{data['field_key']}' is not a photo/file field",
                }
            ],
        )
    if data["size"] > MAX_SIZE:
        raise UnprocessableEntity(
            "File too large",
            errors=[{"field": "size", "code": "max", "message": f"At most {MAX_SIZE} bytes"}],
        )
    key = storage_key(feature, data["id"], data["content_type"])
    upload_id = storage.start_multipart(key, data["content_type"])
    att = Attachment.objects.create(
        id=data["id"],
        org=feature.org,
        feature=feature,
        project=feature.project,
        field_key=data["field_key"],
        content_type=data["content_type"],
        size=data["size"],
        checksum_sha256=data["checksum_sha256"].lower(),
        storage_key=key,
        upload_status=UploadStatus.UPLOADING,
        upload_id=upload_id,
        part_size=storage.PART_SIZE,
        captured_at=data.get("captured_at"),
        created_by=user,
        device=device,
    )
    return att, list(range(1, storage.part_count(att.size, att.part_size) + 1))


def resume_upload(att: Attachment) -> tuple[Attachment, list[int]]:
    """Parts the store already holds are skipped; the rest get fresh presigned URLs."""
    if att.upload_status == UploadStatus.COMPLETE:
        raise Conflict("This attachment is already uploaded")
    if att.upload_status == UploadStatus.FAILED or not att.upload_id:
        att.upload_id = storage.start_multipart(att.storage_key, att.content_type)
        att.upload_status = UploadStatus.UPLOADING
        att.failure_reason = ""
        att.save(update_fields=["upload_id", "upload_status", "failure_reason", "updated_at"])
    have = {p.part_number for p in storage.list_parts(att.storage_key, att.upload_id)}
    total = storage.part_count(att.size, att.part_size)
    return att, [n for n in range(1, total + 1) if n not in have]


def complete_upload(att: Attachment, parts: list[dict[str, Any]]) -> Attachment:
    failure: str | None = None
    with transaction.atomic():
        att = Attachment.objects.select_for_update().get(pk=att.pk)
        if att.upload_status == UploadStatus.COMPLETE:
            return att  # idempotent
        if att.upload_status != UploadStatus.UPLOADING:
            raise Conflict(
                f"Upload is {att.upload_status}; start again with GET /attachments/{{id}}/upload"
            )
        stored = storage.list_parts(att.storage_key, att.upload_id)
        etags = {p.part_number: p.etag for p in stored}
        expected = storage.part_count(att.size, att.part_size)
        missing = [n for n in range(1, expected + 1) if n not in etags]
        if missing:
            raise UnprocessableEntity(
                f"{len(missing)} part(s) not uploaded yet",
                errors=[
                    {
                        "field": "parts",
                        "code": "missing_parts",
                        "message": f"Missing parts: {missing[:20]}",
                    }
                ],
            )
        sent = {int(p["part_number"]): str(p["etag"]) for p in parts} if parts else {}
        for n, etag in sent.items():
            if n in etags and etag.strip('"') != etags[n].strip('"'):
                raise UnprocessableEntity(
                    "Part ETag mismatch",
                    errors=[
                        {
                            "field": "parts",
                            "code": "etag_mismatch",
                            "message": f"Part {n} does not match the stored part",
                        }
                    ],
                )
        storage.complete_multipart(att.storage_key, att.upload_id, list(etags.items()))
        meta = storage.head(att.storage_key)
        actual_size = int(meta["ContentLength"]) if meta else -1
        if actual_size != att.size:
            failure = f"size mismatch: expected {att.size}, stored {actual_size}"
        elif storage.sha256_of(att.storage_key) != att.checksum_sha256:
            failure = "checksum mismatch"
        else:
            att.upload_status = UploadStatus.COMPLETE
            att.completed_at = timezone.now()
            att.upload_id = ""
            att.save(update_fields=["upload_status", "completed_at", "upload_id", "updated_at"])
            from precisecapture.attachments.tasks import post_process

            transaction.on_commit(lambda: post_process.delay(str(att.org_id), str(att.id)))
            return att
    # Outside the savepoint so the failed status survives the error response.
    return _fail(att, failure or "verification failed")


def _fail(att: Attachment, reason: str) -> Attachment:
    storage.delete(att.storage_key)
    att.upload_status = UploadStatus.FAILED
    att.failure_reason = reason
    att.upload_id = ""
    att.save(update_fields=["upload_status", "failure_reason", "upload_id", "updated_at"])
    field = "checksum_sha256" if "checksum" in reason else "size"
    raise UnprocessableEntity(
        f"Upload rejected: {reason}",
        errors=[{"field": field, "code": "mismatch", "message": reason}],
    )


def attachment_out(att: Attachment) -> dict[str, Any]:
    complete = att.upload_status == UploadStatus.COMPLETE
    return {
        "id": att.id,
        "feature_id": att.feature_id,
        "field_key": att.field_key,
        "content_type": att.content_type,
        "size": att.size,
        "upload_status": att.upload_status,
        "failure_reason": att.failure_reason or None,
        "download_url": storage.presign_get(
            att.storage_key, filename=att.storage_key.rsplit("/", 1)[-1]
        )
        if complete
        else None,
        "thumbnail_url": storage.presign_get(att.thumbnail_key)
        if complete and att.thumbnail_key
        else None,
        "metadata": {
            **att.metadata,
            **(
                {"exif_lat": att.exif_lat, "exif_lon": att.exif_lon}
                if att.exif_lat is not None
                else {}
            ),
            **({"exif_time": att.exif_time.isoformat()} if att.exif_time else {}),
        },
        "captured_at": att.captured_at,
        "created_at": att.created_at,
    }


def missing_attachments(project: Project) -> list[dict[str, Any]]:
    """Features whose required media fields (min >= 1 or required) have no completed upload."""
    out: list[dict[str, Any]] = []
    complete: dict[tuple[uuid.UUID, str], int] = {}
    for fid, key in Attachment.objects.filter(
        project=project, upload_status=UploadStatus.COMPLETE
    ).values_list("feature_id", "field_key"):
        complete[(fid, key)] = complete.get((fid, key), 0) + 1
    for feature in Feature.objects.select_related("layer").filter(project=project, deleted=False):
        fields = _media_fields(feature)
        required = [
            k for k, f in fields.items() if f.get("required") is True or (f.get("min") or 0) >= 1
        ]
        missing = [
            k
            for k in required
            if complete.get((feature.id, k), 0) < max(1, int(fields[k].get("min") or 1))
        ]
        if missing:
            out.append(
                {
                    "feature_id": feature.id,
                    "layer_id": feature.layer_id,
                    "layer_key": feature.layer.key,
                    "missing_fields": missing,
                }
            )
    return out
