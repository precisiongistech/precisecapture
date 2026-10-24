"""Attachments: files in object storage, metadata in Postgres (ENGINEERING_NOTES.md §5)."""

from typing import Any

from django.conf import settings as django_settings
from django.db import models

from precisecapture.common.models import TenantModel
from precisecapture.features.models import Feature
from precisecapture.projects.models import Project


class UploadStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    UPLOADING = "uploading", "Uploading"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"


class Attachment(TenantModel):
    # id: client-generated UUIDv7
    feature = models.ForeignKey(Feature, on_delete=models.PROTECT, related_name="attachments")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="attachments")
    field_key = models.CharField(max_length=63)
    content_type = models.CharField(max_length=120)
    size = models.BigIntegerField()
    checksum_sha256 = models.CharField(max_length=64)
    # org/{org_id}/project/{project_id}/feature/{feature_id}/{attachment_id}.{ext}
    storage_key = models.CharField(max_length=500, unique=True)
    upload_status = models.CharField(
        max_length=16, choices=UploadStatus.choices, default=UploadStatus.PENDING
    )
    upload_id = models.CharField(max_length=500, blank=True, default="")
    part_size = models.PositiveIntegerField()
    failure_reason = models.CharField(max_length=200, blank=True, default="")
    captured_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # From EXIF (images), filled by the post-processing task
    exif_lat = models.FloatField(null=True, blank=True)
    exif_lon = models.FloatField(null=True, blank=True)
    exif_time = models.DateTimeField(null=True, blank=True)
    thumbnail_key = models.CharField(max_length=500, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    device = models.ForeignKey(
        "accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        db_table = "attachments_attachment"
        indexes = [
            models.Index(fields=["feature", "field_key"]),
            models.Index(fields=["project", "upload_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.field_key}:{self.id} ({self.upload_status})"

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")


_ = Any
