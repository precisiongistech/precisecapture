from django.db import models

from precisecapture.common.models import UUIDv7Model


class Widget(UUIDv7Model):
    """A concrete model for exercising the base model and pagination helpers."""

    name = models.CharField(max_length=50)
