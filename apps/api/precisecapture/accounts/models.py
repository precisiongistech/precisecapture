"""
Users and devices. Both are global tables (no org_id): a user can belong to several
organisations; a device belongs to a user (ENGINEERING_NOTES.md §1, table list).
"""

from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from precisecapture.common.models import UUIDv7Model

E164 = RegexValidator(
    r"^\+[1-9]\d{6,14}$", "Phone numbers must be in E.164 format, e.g. +233241234567."
)


def normalise_phone(value: str | None) -> str | None:
    """Strip spaces, dashes and dots; convert a leading 00 to +. Returns None for blanks."""
    if value is None:
        return None
    cleaned = "".join(ch for ch in value if ch not in " -.()")
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned or None


def normalise_email(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create(
        self, *, email: str | None, phone: str | None, password: str | None, **extra: Any
    ) -> "User":
        user = self.model(email=normalise_email(email), phone=normalise_phone(phone), **extra)
        user.set_password(password) if password else user.set_unusable_password()
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(
        self,
        email: str | None = None,
        phone: str | None = None,
        password: str | None = None,
        **extra: Any,
    ) -> "User":
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email=email, phone=phone, password=password, **extra)

    def create_superuser(self, email: str, password: str, **extra: Any) -> "User":
        """Platform staff only (Django admin on the internal deployment)."""
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create(email=email, phone=None, password=password, **extra)

    def by_identifier(self, identifier: str) -> "User | None":
        """Find a user by email or E.164 phone, whichever the string looks like."""
        ident = identifier.strip()
        if "@" in ident:
            return self.filter(email=normalise_email(ident)).first()
        return self.filter(phone=normalise_phone(ident)).first()


class User(UUIDv7Model, AbstractBaseUser, PermissionsMixin):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    email = models.EmailField(null=True, blank=True, unique=True)
    phone = models.CharField(max_length=16, null=True, blank=True, unique=True, validators=[E164])
    name = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    is_staff = models.BooleanField(
        default=False, help_text="Platform staff: may use the internal admin."
    )
    last_login_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects: ClassVar[UserManager] = UserManager()

    class Meta(UUIDv7Model.Meta):
        db_table = "accounts_user"
        constraints = [
            models.CheckConstraint(
                condition=Q(email__isnull=False) | Q(phone__isnull=False),
                name="accounts_user_email_or_phone",
            )
        ]

    def __str__(self) -> str:
        return self.email or self.phone or str(self.id)

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return self.status == self.Status.ACTIVE

    def clean(self) -> None:
        super().clean()
        self.email = normalise_email(self.email)
        self.phone = normalise_phone(self.phone)
        if not self.email and not self.phone:
            raise ValidationError("A user needs an email address or a phone number.")

    def mark_login(self) -> None:
        self.last_login_at = timezone.now()
        self.save(update_fields=["last_login_at", "updated_at"])


class Device(UUIDv7Model):
    """A phone (or browser) the user has registered. Refresh tokens are bound to it."""

    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        WEB = "web", "Web"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    platform = models.CharField(max_length=16, choices=Platform.choices)
    model = models.CharField(max_length=120, blank=True)
    os_version = models.CharField(max_length=60, blank=True)
    app_version = models.CharField(max_length=40, blank=True)
    push_token = models.CharField(max_length=255, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta(UUIDv7Model.Meta):
        db_table = "accounts_device"
        indexes = [models.Index(fields=["user", "platform"])]

    def __str__(self) -> str:
        return f"{self.platform} {self.model} ({self.user})"


class RefreshToken(UUIDv7Model):
    """
    Opaque refresh token, stored hashed, rotated on every use (ENGINEERING_NOTES.md §6).

    All tokens issued by rotation from one login share a `family`. Presenting a token that
    was already rotated means it leaked: the whole family is revoked.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_tokens")
    device = models.ForeignKey(
        Device, null=True, blank=True, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    family = models.UUIDField(db_index=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    replaced_by = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replaces"
    )
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta(UUIDv7Model.Meta):
        db_table = "accounts_refreshtoken"
        indexes = [models.Index(fields=["user", "revoked_at"])]

    @property
    def is_active(self) -> bool:
        return (
            self.revoked_at is None
            and self.replaced_by_id is None
            and self.expires_at > timezone.now()
        )
