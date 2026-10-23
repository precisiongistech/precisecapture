"""
Projects, members, layers, layer schema versions and templates. All tenant tables
(org_id + RLS; see the migration), SPEC.md §7 and §9, DECISIONS.md (layer keys).
"""

from typing import Any, ClassVar

from django.conf import settings as django_settings
from django.contrib.gis.db import models as gis
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F

from precisecapture.common.models import TenantModel

LAYER_KEY = RegexValidator(
    r"^[a-z][a-z0-9_]{0,62}$", "Keys start with a letter and use lowercase letters, digits and _."
)


class GeometryType(models.TextChoices):
    POINT = "point", "Point"
    LINE = "line", "Line"
    POLYGON = "polygon", "Polygon"
    NONE = "none", "No geometry (table)"


class ProjectRole(models.TextChoices):
    MANAGER = "manager", "Manager"
    COLLECTOR = "collector", "Collector"
    VIEWER = "viewer", "Viewer"


class Project(TenantModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    extent = gis.PolygonField(srid=4326, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    # Project-level partial capture profile lives at settings["capture_profile"].
    settings = models.JSONField(default=dict, blank=True)
    # Bumped by every change the phone must re-download (layers, schemas, profiles, members).
    config_version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    layers: ClassVar[models.Manager["Layer"]]
    members: ClassVar[models.Manager["ProjectMember"]]

    class Meta(TenantModel.Meta):
        db_table = "projects_project"
        indexes = [models.Index(fields=["org", "status"])]

    def __str__(self) -> str:
        return self.name

    @property
    def capture_profile(self) -> dict[str, Any]:
        value = self.settings.get("capture_profile") if isinstance(self.settings, dict) else None
        return value if isinstance(value, dict) else {}

    def bump_config_version(self) -> None:
        Project.all_tenants.filter(pk=self.pk).update(config_version=F("config_version") + 1)
        self.refresh_from_db(fields=["config_version"])


class ProjectMember(TenantModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    role = models.CharField(
        max_length=16, choices=ProjectRole.choices, default=ProjectRole.COLLECTOR
    )
    # Limits what a collector downloads and where they may capture (used from M5/M6).
    assigned_area = gis.MultiPolygonField(srid=4326, null=True, blank=True)
    # Bumped on every change to this row; part of the bundle ETag.
    version = models.PositiveIntegerField(default=1)

    class Meta(TenantModel.Meta):
        db_table = "projects_projectmember"
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="projects_member_project_user")
        ]
        indexes = [models.Index(fields=["user", "org"])]

    def __str__(self) -> str:
        return f"{self.user} @ {self.project} ({self.role})"


class Layer(TenantModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="layers")
    name = models.CharField(max_length=160)
    # Project-unique slug used inside schemas and profiles; API paths use the UUID.
    key = models.CharField(max_length=63, validators=[LAYER_KEY])
    geometry_type = models.CharField(max_length=16, choices=GeometryType.choices)
    style = models.JSONField(default=dict, blank=True)
    capture_profile = models.JSONField(default=dict, blank=True)
    # The attribute list being edited; publishing copies it into a LayerSchemaVersion.
    draft_schema = models.JSONField(null=True, blank=True)
    current_schema_version = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)
    schema_versions: ClassVar[models.Manager["LayerSchemaVersion"]]

    class Meta(TenantModel.Meta):
        db_table = "projects_layer"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["project", "key"], name="projects_layer_project_key")
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"


class LayerSchemaVersion(TenantModel):
    """Immutable once published: features record the version they were captured with."""

    layer = models.ForeignKey(Layer, on_delete=models.CASCADE, related_name="schema_versions")
    version = models.PositiveIntegerField()
    attributes = models.JSONField()
    published_at = models.DateTimeField(auto_now_add=True)
    published_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        db_table = "projects_layerschemaversion"
        ordering = ["layer", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["layer", "version"], name="projects_schemaversion_layer_version"
            )
        ]

    def __str__(self) -> str:
        return f"{self.layer.key} v{self.version}"


class LayerTemplate(TenantModel):
    """A saved layer (attributes + capture profile) reusable across the organisation's projects."""

    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    geometry_type = models.CharField(max_length=16, choices=GeometryType.choices)
    attributes = models.JSONField()
    capture_profile = models.JSONField(default=dict, blank=True)
    style = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        db_table = "projects_layertemplate"
        constraints = [
            models.UniqueConstraint(fields=["org", "name"], name="projects_template_org_name")
        ]

    def __str__(self) -> str:
        return self.name
