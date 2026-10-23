from django.db import models

from precisecapture.common.ids import uuid7


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
