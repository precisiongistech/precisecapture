"""
Sync bookkeeping (ENGINEERING_NOTES.md §2). All tenant tables.

ProjectSyncState is locked FOR UPDATE for the whole push transaction, and every applied
change takes its seq inside that lock, so commit order equals seq order and pull cursors
never miss rows.
"""

from typing import Any

from django.conf import settings as django_settings
from django.db import models

from precisecapture.common.models import TenantModel
from precisecapture.features.models import Feature
from precisecapture.projects.models import Project


class ProjectSyncState(TenantModel):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="sync_state")
    last_seq = models.BigIntegerField(default=0)

    class Meta(TenantModel.Meta):
        db_table = "sync_projectsyncstate"

    def __str__(self) -> str:
        return f"{self.project_id} @ {self.last_seq}"


class ChangeOp(models.TextChoices):
    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"


class ChangeLog(TenantModel):
    """One row per applied change, gap-free per project; pull reads it in seq order."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="changelog")
    seq = models.BigIntegerField()
    entity = models.CharField(max_length=16, default="feature")
    entity_id = models.UUIDField()
    op = models.CharField(max_length=8, choices=ChangeOp.choices)
    feature_version = models.PositiveIntegerField()
    changed_at = models.DateTimeField(auto_now_add=True)
    device = models.ForeignKey(
        "accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    change_id = models.UUIDField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        db_table = "sync_changelog"
        ordering = ["project", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["project", "seq"], name="sync_changelog_project_seq")
        ]
        indexes = [models.Index(fields=["project", "entity_id"])]

    def __str__(self) -> str:
        return f"{self.project_id}#{self.seq} {self.op} {self.entity_id}"


class AppliedChange(TenantModel):
    """Idempotency on change_id: the stored result is returned on replay."""

    change_id = models.UUIDField(unique=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="+")
    device = models.ForeignKey(
        "accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    result = models.JSONField()
    seq = models.BigIntegerField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        db_table = "sync_appliedchange"

    def __str__(self) -> str:
        return str(self.change_id)


class SyncCursor(TenantModel):
    """Where each device is up to, plus support metrics."""

    device = models.ForeignKey(
        "accounts.Device", on_delete=models.CASCADE, related_name="sync_cursors"
    )
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sync_cursors")
    last_pulled_seq = models.BigIntegerField(default=0)
    last_pull_at = models.DateTimeField(null=True, blank=True)
    last_push_at = models.DateTimeField(null=True, blank=True)
    pushed_changes = models.PositiveIntegerField(default=0)
    pulled_items = models.PositiveIntegerField(default=0)
    rejected_changes = models.PositiveIntegerField(default=0)
    conflicts = models.PositiveIntegerField(default=0)
    last_push_ms = models.PositiveIntegerField(null=True, blank=True)
    last_pull_ms = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        db_table = "sync_synccursor"
        constraints = [
            models.UniqueConstraint(fields=["device", "project"], name="sync_cursor_device_project")
        ]

    def __str__(self) -> str:
        return f"{self.device_id} / {self.project_id} @ {self.last_pulled_seq}"


class Conflict(TenantModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    class Resolution(models.TextChoices):
        KEEP_SERVER = "keep_server", "Keep server"
        KEEP_DEVICE = "keep_device", "Keep device"
        MERGED = "merged", "Merged"

    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="conflicts")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="conflicts")
    device = models.ForeignKey(
        "accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    change_id = models.UUIDField(null=True, blank=True)
    reason = models.CharField(max_length=40)
    base_version = models.PositiveIntegerField(null=True, blank=True)
    server_version = models.PositiveIntegerField()
    local_payload = models.JSONField()
    server_payload = models.JSONField()
    overlapping_fields = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    resolution = models.CharField(max_length=16, choices=Resolution.choices, blank=True, default="")
    resolved_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        db_table = "sync_conflict"
        indexes = [models.Index(fields=["project", "status"])]

    def __str__(self) -> str:
        return f"{self.feature_id} ({self.reason}, {self.status})"


_ = Any
