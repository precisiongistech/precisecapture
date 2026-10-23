from typing import Any, TypeVar

from django.db import models

from precisecapture.common.ids import uuid7
from precisecapture.common.tenancy import current_org_id, require_org_id


class UUIDv7Model(models.Model):
    """
    Base for every table: UUIDv7 primary key plus timestamps.

    Client-generated ids (features, attachments, sync changes) are passed in explicitly;
    the default only applies to rows the server creates itself.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["id"]  # UUIDv7 sorts by creation time


_T = TypeVar("_T", bound="TenantModel")


class TenantManager(models.Manager[_T]):
    """
    Default manager for tenant tables: filters by the current org from the contextvar.

    RLS in the database is the guarantee; this makes the intent visible in code and keeps
    accidental cross-tenant queries from even reaching Postgres. Outside a tenant context the
    queryset is empty (fail closed), mirroring the policy.
    """

    def get_queryset(self) -> models.QuerySet[_T]:
        qs = super().get_queryset()
        org_id = current_org_id()
        return qs.filter(org_id=org_id) if org_id is not None else qs.none()


class TenantModel(UUIDv7Model):
    """
    Base for every tenant-owned table: an `org_id` column plus RLS (added in the migration
    with `enable_rls(table)`) and the tenant default manager.

    `org_id` is copied onto every row even when derivable from a parent, because policies
    must not join. New rows default to the current tenant.
    """

    org = models.ForeignKey(
        "orgs.Organisation", on_delete=models.CASCADE, related_name="+", editable=False
    )

    objects = TenantManager()
    all_tenants = models.Manager()  # noqa: DJ012  (bypasses the filter: tests and platform jobs only)

    class Meta(UUIDv7Model.Meta):
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        if getattr(self, "org_id", None) is None:
            self.org_id = require_org_id()
        super().save(*args, **kwargs)


class IdempotencyKey(models.Model):
    """
    Idempotency-Key support for non-sync writes: the first response for (user, key, method,
    path) is stored and replayed for 24 hours. Global table scoped by user id.
    """

    user_id = models.UUIDField()
    key = models.CharField(max_length=200)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=500)
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    response_body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "common_idempotencykey"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "key", "method", "path"], name="common_idempotency_unique"
            )
        ]
        indexes = [models.Index(fields=["created_at"])]

    def __str__(self) -> str:
        return f"{self.method} {self.path} [{self.key}]"
