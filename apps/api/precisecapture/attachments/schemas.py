"""Resumable attachment uploads (ENGINEERING_NOTES.md §5)."""

import uuid
from datetime import datetime
from typing import Any

from ninja import Field, Schema

UUID_ATTACHMENT = "0192f0c1-1234-7abc-8def-0000000000cc"
UUID_FEATURE = "0192f0c1-1234-7abc-8def-000000000001"


class AttachmentCreateIn(Schema):
    id: uuid.UUID = Field(..., description="Client-generated UUIDv7", examples=[UUID_ATTACHMENT])
    feature_id: uuid.UUID = Field(..., examples=[UUID_FEATURE])
    field_key: str = Field(..., examples=["photos"])
    content_type: str = Field(..., examples=["image/jpeg"])
    size: int = Field(..., ge=1, examples=[2_345_678])
    checksum_sha256: str = Field(
        ...,
        pattern="^[a-f0-9]{64}$",
        examples=["9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"],
    )
    captured_at: datetime | None = Field(None, examples=["2026-10-22T10:15:02Z"])


class PartUrl(Schema):
    part_number: int = Field(..., ge=1, examples=[1])
    url: str = Field(
        ...,
        examples=[
            "https://spaces.example/bucket/org/.../0192f0c1...jpg?partNumber=1&uploadId=abc&X-Amz-Signature=..."
        ],
    )


class AttachmentUploadOut(Schema):
    id: uuid.UUID = Field(..., examples=[UUID_ATTACHMENT])
    upload_id: str = Field(..., examples=["2~abc123"])
    part_size: int = Field(..., description="Bytes per part", examples=[8_388_608])
    parts: list[PartUrl]
    expires_at: datetime = Field(..., examples=["2026-10-22T11:15:02Z"])


class PartEtag(Schema):
    part_number: int = Field(..., ge=1, examples=[1])
    etag: str = Field(..., examples=['"d41d8cd98f00b204e9800998ecf8427e"'])


class AttachmentCompleteIn(Schema):
    upload_id: str = Field(..., examples=["2~abc123"])
    parts: list[PartEtag]


class AttachmentOut(Schema):
    id: uuid.UUID = Field(..., examples=[UUID_ATTACHMENT])
    feature_id: uuid.UUID = Field(..., examples=[UUID_FEATURE])
    field_key: str = Field(..., examples=["photos"])
    content_type: str = Field(..., examples=["image/jpeg"])
    size: int = Field(..., examples=[2_345_678])
    upload_status: str = Field(..., examples=["complete"])
    failure_reason: str | None = None
    download_url: str | None = Field(
        None,
        description="Presigned GET, valid 15 minutes",
        examples=["https://spaces.example/...?X-Amz-Signature=..."],
    )
    thumbnail_url: str | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict, examples=[{"exif_lat": 6.2, "exif_lon": -2.5}]
    )
    created_at: datetime = Field(..., examples=["2026-10-22T10:16:00Z"])


ATTACHMENT_UPLOAD_EXAMPLE: dict[str, Any] = {
    "id": UUID_ATTACHMENT,
    "upload_id": "2~abc123",
    "part_size": 8_388_608,
    "parts": [
        {
            "part_number": 1,
            "url": "https://spaces.example/bucket/key?partNumber=1&uploadId=2~abc123&X-Amz-Signature=sig",
        }
    ],
    "expires_at": "2026-10-22T11:15:02Z",
}


class MissingAttachmentsOut(Schema):
    feature_id: uuid.UUID
    layer_id: uuid.UUID
    layer_key: str
    missing_fields: list[str]
