"""
Features and their audit trail. All tenant tables (SPEC.md §7, ENGINEERING_NOTES.md §3).

Feature ids are client-generated UUIDv7 (never reassigned). Geometry is EPSG:4326; derived
measures are computed on the geography type and stored. `geometry_type` is copied from the
layer so a CHECK constraint can enforce the geometry shape without a join.
"""

from typing import Any, ClassVar

from django.conf import settings as django_settings
from django.contrib.gis.db import models as gis
from django.contrib.postgres.fields import ArrayField
from django.db import models

from precisecapture.common.models import TenantModel
from precisecapture.projects.models import GeometryType, Layer, Project


class FeatureStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    SENT_BACK = "sent_back", "Sent back"


class CentroidMethod(models.TextChoices):
    CENTROID = "centroid", "Centroid"
    POINT_ON_SURFACE = "point_on_surface", "Point on surface"


# The geometry-type CHECK constraint uses PostGIS GeometryType(), which the ORM cannot
# express, so the migration adds it with RunSQL (see migrations/0001_initial.py).
GEOMETRY_CHECK_SQL = (
    "ALTER TABLE features_feature ADD CONSTRAINT features_feature_geom_matches_type CHECK ("
    "(geometry_type = 'none' AND geom IS NULL) OR "
    "(geometry_type = 'point' AND GeometryType(geom) = 'POINT') OR "
    "(geometry_type = 'line' AND GeometryType(geom) = 'LINESTRING') OR "
    "(geometry_type = 'polygon' AND GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON')))"
)
GEOMETRY_CHECK_REVERSE_SQL = (
    "ALTER TABLE features_feature DROP CONSTRAINT IF EXISTS features_feature_geom_matches_type"
)


class Feature(TenantModel):
    # id: client-generated UUIDv7 (UUIDv7Model default only applies to server-created rows)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="features")
    layer = models.ForeignKey(Layer, on_delete=models.PROTECT, related_name="features")
    geometry_type = models.CharField(max_length=16, choices=GeometryType.choices)
    geom = gis.GeometryField(srid=4326, null=True, blank=True, spatial_index=True)
    attributes = models.JSONField(default=dict, blank=True)
    schema_version = models.PositiveIntegerField()
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16, choices=FeatureStatus.choices, default=FeatureStatus.SUBMITTED
    )
    review_note = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_device = models.ForeignKey(
        "accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_device = models.ForeignKey(
        "accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    captured_at = models.DateTimeField(null=True, blank=True)

    # Server-computed on every write (geography: metres / square metres)
    area_m2 = models.FloatField(null=True, blank=True)
    perimeter_m = models.FloatField(null=True, blank=True)
    length_m = models.FloatField(null=True, blank=True)
    centroid = gis.PointField(srid=4326, null=True, blank=True, spatial_index=False)
    centroid_method = models.CharField(
        max_length=20, choices=CentroidMethod.choices, blank=True, default=""
    )
    qa_flags = ArrayField(models.CharField(max_length=40), default=list, blank=True)

    history: ClassVar[models.Manager["FeatureHistory"]]

    class Meta(TenantModel.Meta):
        db_table = "features_feature"
        indexes = [
            models.Index(fields=["layer", "deleted", "status"]),
            models.Index(fields=["project", "updated_at"]),
            models.Index(fields=["layer", "updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.layer_id}:{self.id} v{self.version}"

    @property
    def area_ha(self) -> float | None:
        return self.area_m2 / 10_000 if self.area_m2 is not None else None

    @property
    def area_acres(self) -> float | None:
        return self.area_m2 / 4046.8564224 if self.area_m2 is not None else None


class ChangeType(models.TextChoices):
    CREATE = "create", "Create"
    UPDATE = "update", "Update"
    DELETE = "delete", "Delete"
    RESTORE = "restore", "Restore"
    REVIEW = "review", "Review"
    MERGE = "merge", "Merge"


class FeatureHistory(TenantModel):
    """Full copy of the feature at every version: the audit trail and the merge base for sync."""

    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="history")
    version = models.PositiveIntegerField()
    change_type = models.CharField(max_length=16, choices=ChangeType.choices)
    geom = gis.GeometryField(srid=4326, null=True, blank=True, spatial_index=False)
    attributes = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=FeatureStatus.choices)
    review_note = models.TextField(blank=True, default="")
    deleted = models.BooleanField(default=False)
    changed_fields = ArrayField(models.CharField(max_length=80), default=list, blank=True)
    changed_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    device = models.ForeignKey(
        "accounts.Device", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    change_id = models.UUIDField(
        null=True, blank=True, help_text="Sync change id when the write came from a device"
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantModel.Meta):
        db_table = "features_featurehistory"
        ordering = ["feature", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["feature", "version"], name="features_history_feature_version"
            )
        ]


class FeatureRelation(TenantModel):
    """Materialised relation attributes (farm -> farmer), kept in step on every write."""

    from_feature = models.ForeignKey(
        Feature, on_delete=models.CASCADE, related_name="relations_out"
    )
    to_feature = models.ForeignKey(Feature, on_delete=models.PROTECT, related_name="relations_in")
    attribute_key = models.CharField(max_length=63)

    class Meta(TenantModel.Meta):
        db_table = "features_featurerelation"
        constraints = [
            models.UniqueConstraint(
                fields=["from_feature", "attribute_key"], name="features_relation_from_key"
            )
        ]
        indexes = [models.Index(fields=["to_feature"])]


class RawTrack(TenantModel):
    """Unsimplified streamed points for audit; never returned in pull."""

    feature = models.OneToOneField(Feature, on_delete=models.CASCADE, related_name="raw_track")
    # [[lon, lat, accuracy_m, epoch_ms], ...]
    points = models.JSONField(default=list)
    point_count = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        db_table = "features_rawtrack"


class VertexMeta(TenantModel):
    """Optional per-vertex GPS quality."""

    feature = models.ForeignKey(Feature, on_delete=models.CASCADE, related_name="vertex_meta")
    vertex_index = models.PositiveIntegerField()
    accuracy_m = models.FloatField(null=True, blank=True)
    fix_type = models.CharField(max_length=20, blank=True, default="")
    satellites = models.PositiveSmallIntegerField(null=True, blank=True)
    timestamp = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=20, blank=True, default="")

    class Meta(TenantModel.Meta):
        db_table = "features_vertexmeta"
        constraints = [
            models.UniqueConstraint(
                fields=["feature", "vertex_index"], name="features_vertexmeta_feature_index"
            )
        ]


__all__: list[str] = [
    "CentroidMethod",
    "ChangeType",
    "Feature",
    "FeatureHistory",
    "FeatureRelation",
    "FeatureStatus",
    "RawTrack",
    "VertexMeta",
]
_ = Any
