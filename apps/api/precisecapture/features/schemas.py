import uuid
from datetime import datetime
from typing import Any

from ninja import Field, Schema

GeoJSON = dict[str, Any]


class FeatureCreateIn(Schema):
    id: uuid.UUID | None = Field(None, description="Client-generated UUIDv7; the server keeps it")
    geom: GeoJSON | None = Field(
        None, description="GeoJSON geometry in EPSG:4326 (null for table layers)"
    )
    attributes: dict[str, Any] = Field(default_factory=dict)
    status: str | None = Field(None, pattern="^(draft|submitted)$")
    schema_version: int | None = Field(None, description="Defaults to the layer's current version")
    captured_at: datetime | None = None


class FeaturePatchIn(Schema):
    geom: GeoJSON | None = None
    attributes: dict[str, Any] | None = None
    status: str | None = Field(None, pattern="^(draft|submitted)$")
    base_version: int | None = Field(
        None, description="Version you edited; 409 when stale (or use If-Match)"
    )


class ReviewIn(Schema):
    action: str = Field(..., pattern="^(approve|reject|send_back)$")
    note: str = ""


class ComputedOut(Schema):
    area_m2: float | None
    area_ha: float | None
    area_acres: float | None
    perimeter_m: float | None
    length_m: float | None
    centroid: GeoJSON | None
    centroid_method: str | None


class FeatureOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    layer_id: uuid.UUID
    layer_key: str
    geometry_type: str
    geom: GeoJSON | None
    attributes: dict[str, Any]
    schema_version: int
    version: int
    status: str
    review_note: str
    reviewed_at: datetime | None
    deleted: bool
    computed: ComputedOut
    qa_flags: list[str]
    created_by: uuid.UUID | None
    updated_by: uuid.UUID | None
    created_device: uuid.UUID | None
    updated_device: uuid.UUID | None
    captured_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FeatureDetailOut(FeatureOut):
    raw_track: list[list[float]] | None = None
    vertex_meta: list[dict[str, Any]] = []
    relations: dict[str, uuid.UUID] = Field(
        default_factory=dict, description="attribute key -> related feature id"
    )


class HistoryOut(Schema):
    version: int
    change_type: str
    changed_fields: list[str]
    status: str
    review_note: str
    deleted: bool
    geom: GeoJSON | None
    attributes: dict[str, Any]
    changed_by: uuid.UUID | None
    device: uuid.UUID | None
    change_id: uuid.UUID | None
    changed_at: datetime


class FeatureListParams(Schema):
    bbox: str | None = Field(None, description="minLon,minLat,maxLon,maxLat (EPSG:4326)")
    status: str | None = Field(None, description="Comma-separated statuses")
    updated_since: datetime | None = None
    include_deleted: bool = False
    qa_flag: str | None = Field(None, description="Only features carrying this QA flag")
    cursor: str | None = None
    limit: int = Field(100, ge=1, le=500)
