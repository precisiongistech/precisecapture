"""
Organisations (tenants) and memberships. Both are global tables: they are what a request
uses to decide which tenant it may enter (ENGINEERING_NOTES.md §1).
"""

from typing import Any, ClassVar

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from precisecapture.common.ids import uuid7
from precisecapture.common.models import UUIDv7Model


class Role(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Manager"
    COLLECTOR = "collector", "Collector"
    VIEWER = "viewer", "Viewer"


# Higher number = more rights. require_role("admin") accepts admin and owner.
ROLE_RANK: dict[str, int] = {
    Role.VIEWER: 10,
    Role.COLLECTOR: 20,
    Role.MANAGER: 30,
    Role.ADMIN: 40,
    Role.OWNER: 50,
}


def role_at_least(role: str, minimum: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[minimum]


class Organisation(UUIDv7Model):
    class Plan(models.TextChoices):
        TRIAL = "trial", "Trial"
        STANDARD = "standard", "Standard"
        ENTERPRISE = "enterprise", "Enterprise"

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=80, unique=True)
    country = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2, e.g. GH")
    plan = models.CharField(max_length=16, choices=Plan.choices, default=Plan.TRIAL)
    # Org-level defaults, e.g. {"capture_defaults": {<partial capture profile>}}
    settings = models.JSONField(default=dict, blank=True)
    # Bring-your-own-storage (later milestone): encrypted DSN + bucket. Placeholder for now.
    data_destination = models.JSONField(default=dict, blank=True)
    members: ClassVar[models.Manager["Membership"]]

    class Meta(UUIDv7Model.Meta):
        db_table = "orgs_organisation"

    def __str__(self) -> str:
        return self.name

    @property
    def capture_defaults(self) -> dict[str, Any]:
        value = self.settings.get("capture_defaults") if isinstance(self.settings, dict) else None
        return value if isinstance(value, dict) else {}

    @staticmethod
    def unique_slug(name: str) -> str:
        base = slugify(name)[:60] or "org"
        slug = base
        n = 2
        while Organisation.objects.filter(slug=slug).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug


class Membership(UUIDv7Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    org = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="members")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.COLLECTOR)
    # Bumped whenever role or project assignments change; part of the bundle ETag (M3).
    version = models.PositiveIntegerField(default=1)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(UUIDv7Model.Meta):
        db_table = "orgs_membership"
        constraints = [
            models.UniqueConstraint(fields=["user", "org"], name="orgs_membership_user_org")
        ]
        indexes = [models.Index(fields=["org", "role"])]

    def __str__(self) -> str:
        return f"{self.user} @ {self.org} ({self.role})"

    def bump_version(self) -> None:
        self.version += 1
        self.save(update_fields=["version", "updated_at"])


class Invitation(UUIDv7Model):
    """
    An invitation to join an organisation, sent by email or SMS with a one-time token.
    Global table (resolved by token before a tenant is known), see ENGINEERING_NOTES.md §1.
    """

    org = models.ForeignKey(Organisation, on_delete=models.CASCADE, related_name="invitations")
    # NULL (not "") so "no email" and "no phone" are unambiguous, as on accounts.User.
    email = models.EmailField(null=True, blank=True)  # noqa: DJ001
    phone = models.CharField(max_length=16, null=True, blank=True)  # noqa: DJ001
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.COLLECTOR)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta(UUIDv7Model.Meta):
        db_table = "orgs_invitation"
        indexes = [models.Index(fields=["org", "accepted_at"])]

    @property
    def destination(self) -> str:
        return self.email or self.phone or ""

    @property
    def is_open(self) -> bool:
        return (
            self.accepted_at is None
            and self.revoked_at is None
            and self.expires_at > timezone.now()
        )


__all__ = [
    "ROLE_RANK",
    "Invitation",
    "Membership",
    "Organisation",
    "Role",
    "role_at_least",
    "uuid7",
]
