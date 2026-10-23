import uuid
from datetime import datetime
from typing import Any

from ninja import Field, Schema

GeoJSON = dict[str, Any]


class ProjectIn(Schema):
    name: str = Field(..., min_length=2, max_length=160)
    description: str = ""
    extent: GeoJSON | None = Field(None, description="GeoJSON Polygon in EPSG:4326")
    status: str = Field("draft", pattern="^(draft|active|archived)$")
    settings: dict[str, Any] = Field(
        default_factory=dict, description='May hold "capture_profile" (partial)'
    )


class ProjectPatchIn(Schema):
    name: str | None = Field(None, min_length=2, max_length=160)
    description: str | None = None
    extent: GeoJSON | None = None
    status: str | None = Field(None, pattern="^(draft|active|archived)$")
    settings: dict[str, Any] | None = None


class ProjectOut(Schema):
    id: uuid.UUID
    name: str
    description: str
    extent: GeoJSON | None
    status: str
    settings: dict[str, Any]
    config_version: int
    my_role: str | None = None
    layer_count: int = 0
    created_at: datetime
    updated_at: datetime


class ProjectMemberIn(Schema):
    user_id: uuid.UUID
    role: str = Field("collector", pattern="^(manager|collector|viewer)$")
    assigned_area: GeoJSON | None = Field(None, description="GeoJSON MultiPolygon or Polygon")


class ProjectMemberPatchIn(Schema):
    role: str | None = Field(None, pattern="^(manager|collector|viewer)$")
    assigned_area: GeoJSON | None = None
    clear_assigned_area: bool = False


class ProjectMemberOut(Schema):
    user_id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    role: str
    assigned_area: GeoJSON | None
    version: int


class LayerIn(Schema):
    name: str = Field(..., min_length=1, max_length=160)
    key: str = Field(..., pattern="^[a-z][a-z0-9_]{0,62}$")
    geometry_type: str = Field(..., pattern="^(point|line|polygon|none)$")
    style: dict[str, Any] = Field(default_factory=dict)
    capture_profile: dict[str, Any] = Field(default_factory=dict)
    sort_order: int | None = None


class LayerPatchIn(Schema):
    name: str | None = Field(None, min_length=1, max_length=160)
    style: dict[str, Any] | None = None
    sort_order: int | None = None


class LayerOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    key: str
    geometry_type: str
    style: dict[str, Any]
    capture_profile: dict[str, Any]
    current_schema_version: int
    has_draft: bool = False
    sort_order: int
    created_at: datetime
    updated_at: datetime


class LayerReorderIn(Schema):
    layer_ids: list[uuid.UUID]


class SchemaDraftIn(Schema):
    attributes: dict[str, Any] = Field(..., description="A layer attribute schema document")


class SchemaOut(Schema):
    layer_id: uuid.UUID
    current_version: int
    current: dict[str, Any] | None
    draft: dict[str, Any] | None
    draft_differs: bool


class SchemaVersionOut(Schema):
    version: int
    attributes: dict[str, Any]
    published_at: datetime
    published_by: uuid.UUID | None


class SchemaPublishOut(Schema):
    version: int
    config_version: int
    warnings: list[str] = []


class CaptureProfileIn(Schema):
    capture_profile: dict[str, Any]


class CaptureProfileOut(Schema):
    layer_id: uuid.UUID
    capture_profile: dict[str, Any] = Field(..., description="The layer's own (partial) profile")
    resolved: dict[str, Any] = Field(
        ..., description="org -> project -> layer merge, what the phone obeys"
    )
    config_version: int


class TemplateIn(Schema):
    name: str = Field(..., min_length=1, max_length=160)
    description: str = ""


class TemplateOut(Schema):
    id: uuid.UUID
    name: str
    description: str
    geometry_type: str
    attributes: dict[str, Any]
    capture_profile: dict[str, Any]
    style: dict[str, Any]
    created_at: datetime


class LayerFromTemplateIn(Schema):
    template_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=160)
    key: str = Field(..., pattern="^[a-z][a-z0-9_]{0,62}$")
