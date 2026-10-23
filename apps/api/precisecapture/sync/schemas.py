"""
Wire formats for POST /sync/push and GET /sync/pull.

These mirror packages/schema/schemas/sync.schema.json field for field; a test validates the
examples below against that JSON Schema so the two cannot drift. Implementation lands in M6.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from ninja import Field, Schema

UUID_PROJECT = "01a16990-2368-7736-9254-4cbea027a751"
UUID_LAYER = "01a16990-2a01-7e0e-9b1a-7d2c3f4e5a6b"
UUID_FEATURE = "0192f0c1-1234-7abc-8def-000000000001"
UUID_CHANGE = "0192f0c1-1234-7abc-8def-000000000002"
UUID_DEVICE = "0192f0c1-1234-7abc-8def-000000000003"
UUID_USER = "01a1696a-d6f1-7794-8afd-42b78a877796"

GEOM_EXAMPLE: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[-2.5, 6.2], [-2.499, 6.2], [-2.499, 6.201], [-2.5, 6.201], [-2.5, 6.2]]],
}


class GeoJSONGeometry(Schema):
    type: Literal["Point", "LineString", "Polygon", "MultiPolygon"]
    coordinates: list[Any]


class VertexMeta(Schema):
    i: int = Field(..., ge=0, description="Vertex index")
    accuracy_m: float | None = None
    fix_type: str | None = None
    satellites: int | None = None
    t: datetime | None = None
    source: Literal["phone", "external_gnss", "manual"] | None = None


class ChangeMeta(Schema):
    device_id: uuid.UUID = Field(..., examples=[UUID_DEVICE])
    captured_at: datetime = Field(..., examples=["2026-10-22T10:15:02Z"])
    app_version: str | None = Field(None, examples=["0.1.0"])
    gps_accuracy_m: float | None = Field(None, ge=0, examples=[2.4])
    mock_location: bool | None = Field(None, examples=[False])
    capture_mode: Literal["tap", "gps_vertex", "stream", "hybrid", "external_gnss"] | None = Field(
        None, examples=["stream"]
    )
    stream_interval_m: float | None = Field(None, examples=[3])
    vertex_meta: list[VertexMeta] | None = None
    raw_track: list[list[float]] | None = Field(
        None,
        description="Unsimplified streamed points [lon, lat, accuracy_m, epoch_ms]; sent on create",
    )


class Change(Schema):
    change_id: uuid.UUID = Field(
        ...,
        description="Client-generated UUIDv7; the server is idempotent on it",
        examples=[UUID_CHANGE],
    )
    op: Literal["create", "update", "delete"] = Field(..., examples=["create"])
    entity: Literal["feature"] = "feature"
    id: uuid.UUID = Field(
        ..., description="Feature id, client-generated UUIDv7", examples=[UUID_FEATURE]
    )
    layer_id: uuid.UUID = Field(
        ..., description="Layer UUID from the bundle (not the key)", examples=[UUID_LAYER]
    )
    base_version: int | None = Field(
        ..., ge=0, description="Version the edit started from; null for create", examples=[None]
    )
    schema_version: int = Field(..., ge=1, examples=[1])
    geom: GeoJSONGeometry | None = Field(None, examples=[GEOM_EXAMPLE])
    attributes: dict[str, Any] | None = Field(
        None, examples=[{"crop": "cocoa", "planting_year": 2018}]
    )
    changed_fields: list[str] | None = Field(
        None, description="Attribute keys changed by this edit plus 'geom'; required for update"
    )
    status: Literal["draft", "submitted"] | None = Field(None, examples=["submitted"])
    meta: ChangeMeta


class PushRequest(Schema):
    project_id: uuid.UUID = Field(..., examples=[UUID_PROJECT])
    changes: list[Change] = Field(..., max_length=200)


class ChangeError(Schema):
    field: str | None = None
    code: str
    message: str


class FeatureRef(Schema):
    id: uuid.UUID
    version: int


class ChangeResult(Schema):
    change_id: uuid.UUID = Field(..., examples=[UUID_CHANGE])
    status: Literal["accepted", "merged", "conflict", "rejected", "duplicate"] = Field(
        ..., examples=["accepted"]
    )
    feature: FeatureRef | None = None
    conflict_id: uuid.UUID | None = None
    errors: list[ChangeError] | None = None


class PushResponse(Schema):
    results: list[ChangeResult]
    last_seq: int = Field(..., examples=[42])
    config_version: int | None = Field(None, examples=[8])


class Computed(Schema):
    area_m2: float | None = Field(None, examples=[12345.6])
    length_m: float | None = Field(None, examples=[445.2])
    centroid: GeoJSONGeometry | None = None
    centroid_method: Literal["centroid", "point_on_surface"] | None = Field(
        None, examples=["centroid"]
    )


class PullItem(Schema):
    seq: int = Field(..., examples=[42])
    entity: Literal["feature"] = "feature"
    id: uuid.UUID = Field(..., examples=[UUID_FEATURE])
    layer_id: uuid.UUID = Field(..., examples=[UUID_LAYER])
    version: int = Field(..., examples=[3])
    deleted: bool = Field(..., examples=[False])
    schema_version: int | None = Field(None, examples=[1])
    geom: GeoJSONGeometry | None = Field(None, examples=[GEOM_EXAMPLE])
    attributes: dict[str, Any] | None = Field(None, examples=[{"crop": "cocoa"}])
    status: Literal["draft", "submitted", "approved", "rejected", "sent_back"] | None = Field(
        None, examples=["submitted"]
    )
    review_note: str | None = Field(None, examples=[None])
    computed: Computed | None = None
    qa_flags: list[str] | None = Field(None, examples=[[]])
    updated_at: datetime | None = Field(None, examples=["2026-10-22T10:16:00Z"])
    updated_by: uuid.UUID | None = Field(None, examples=[UUID_USER])


class PullResponse(Schema):
    items: list[PullItem]
    next_cursor: int = Field(..., examples=[42])
    has_more: bool = Field(..., examples=[False])
    config_version: int = Field(..., examples=[8])


# --- examples used in the OpenAPI document and validated against sync.schema.json -----------

PUSH_REQUEST_EXAMPLE: dict[str, Any] = {
    "project_id": UUID_PROJECT,
    "changes": [
        {
            "change_id": UUID_CHANGE,
            "op": "create",
            "entity": "feature",
            "id": UUID_FEATURE,
            "layer_id": UUID_LAYER,
            "base_version": None,
            "schema_version": 1,
            "geom": GEOM_EXAMPLE,
            "attributes": {
                "farmer": "0192f0c1-1234-7abc-8def-0000000000aa",
                "crop": "cocoa",
                "planting_year": 2018,
            },
            "changed_fields": ["geom", "farmer", "crop", "planting_year"],
            "status": "submitted",
            "meta": {
                "device_id": UUID_DEVICE,
                "captured_at": "2026-10-22T10:15:02Z",
                "app_version": "0.1.0",
                "gps_accuracy_m": 2.4,
                "mock_location": False,
                "capture_mode": "stream",
                "stream_interval_m": 3,
            },
        }
    ],
}

PUSH_RESPONSE_EXAMPLE: dict[str, Any] = {
    "results": [
        {
            "change_id": UUID_CHANGE,
            "status": "accepted",
            "feature": {"id": UUID_FEATURE, "version": 1},
        }
    ],
    "last_seq": 42,
    "config_version": 8,
}

PULL_RESPONSE_EXAMPLE: dict[str, Any] = {
    "items": [
        {
            "seq": 42,
            "entity": "feature",
            "id": UUID_FEATURE,
            "layer_id": UUID_LAYER,
            "version": 1,
            "deleted": False,
            "schema_version": 1,
            "geom": GEOM_EXAMPLE,
            "attributes": {
                "farmer": "0192f0c1-1234-7abc-8def-0000000000aa",
                "crop": "cocoa",
                "planting_year": 2018,
            },
            "status": "submitted",
            "review_note": None,
            "computed": {
                "area_m2": 12345.6,
                "length_m": 445.2,
                "centroid": {"type": "Point", "coordinates": [-2.4995, 6.2005]},
                "centroid_method": "centroid",
            },
            "qa_flags": [],
            "updated_at": "2026-10-22T10:16:00Z",
            "updated_by": UUID_USER,
        }
    ],
    "next_cursor": 42,
    "has_more": False,
    "config_version": 8,
}
