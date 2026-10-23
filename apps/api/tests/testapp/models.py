from django.db import models

from precisecapture.common.models import TenantModel, UUIDv7Model


class Widget(UUIDv7Model):
    """A concrete model for exercising the base model and pagination helpers."""

    name = models.CharField(max_length=50)


class Secret(TenantModel):
    """A tenant table that exists only in tests, to prove the RLS plumbing before M3."""

    note = models.CharField(max_length=100)

    class Meta(TenantModel.Meta):
        db_table = "testapp_secret"
