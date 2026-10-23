"""Projects, members and layers. Schema publishing lives in schema_services.py."""

import json
import uuid
from typing import Any

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.db import IntegrityError, transaction

from precisecapture.accounts.models import User
from precisecapture.common.errors import Conflict, NotFound, UnprocessableEntity
from precisecapture.orgs.models import Membership, Organisation, Role, role_at_least
from precisecapture.projects.models import Layer, Project, ProjectMember

# --- geometry helpers ------------------------------------------------------------------


def _bad(field: str, message: str) -> UnprocessableEntity:
    return UnprocessableEntity(
        message, errors=[{"field": field, "code": "invalid", "message": message}]
    )


def geojson_to_polygon(value: dict[str, Any] | None, field: str) -> Polygon | None:
    if value is None:
        return None
    try:
        geom = GEOSGeometry(json.dumps(value), srid=4326)
    except Exception as exc:
        raise _bad(field, f"Invalid GeoJSON: {exc}") from exc
    if not isinstance(geom, Polygon):
        raise _bad(field, "A GeoJSON Polygon is required")
    if not geom.valid:
        raise _bad(field, f"Polygon is not valid: {geom.valid_reason}")
    return geom


def geojson_to_multipolygon(value: dict[str, Any] | None, field: str) -> MultiPolygon | None:
    if value is None:
        return None
    try:
        geom = GEOSGeometry(json.dumps(value), srid=4326)
    except Exception as exc:
        raise _bad(field, f"Invalid GeoJSON: {exc}") from exc
    if isinstance(geom, Polygon):
        geom = MultiPolygon(geom, srid=4326)
    if not isinstance(geom, MultiPolygon):
        raise _bad(field, "A GeoJSON Polygon or MultiPolygon is required")
    if not geom.valid:
        raise _bad(field, f"Geometry is not valid: {geom.valid_reason}")
    return geom


def geom_to_geojson(geom: GEOSGeometry | None) -> dict[str, Any] | None:
    return json.loads(geom.geojson) if geom is not None else None


# --- projects ---------------------------------------------------------------------------


def get_project(project_id: uuid.UUID) -> Project:
    project = Project.objects.filter(pk=project_id).first()
    if project is None:
        raise NotFound("Project not found")
    return project


def project_member_role(project: Project, user: User) -> str | None:
    row = ProjectMember.objects.filter(project=project, user=user).only("role").first()
    return row.role if row else None


def visible_projects(membership: Membership) -> list[Project]:
    """Org managers and above see every project; others see the ones they are assigned to."""
    if role_at_least(membership.role, Role.MANAGER):
        return list(Project.objects.all().order_by("name"))
    ids = ProjectMember.objects.filter(user=membership.user).values_list("project_id", flat=True)
    return list(Project.objects.filter(pk__in=ids).order_by("name"))


def create_project(org: Organisation, creator: User, data: dict[str, Any]) -> Project:
    extent = geojson_to_polygon(data.get("extent"), "extent")
    return Project.objects.create(
        org=org,
        name=data["name"],
        description=data.get("description", ""),
        extent=extent,
        status=data.get("status", Project.Status.DRAFT),
        settings=data.get("settings") or {},
        created_by=creator,
    )


def update_project(project: Project, data: dict[str, Any]) -> Project:
    bump = False
    if "extent" in data:
        project.extent = geojson_to_polygon(data["extent"], "extent")
    for key in ("name", "description", "status"):
        if data.get(key) is not None:
            setattr(project, key, data[key])
    if data.get("settings") is not None:
        bump = data["settings"].get("capture_profile") != project.capture_profile
        project.settings = data["settings"]
    project.save()
    if bump:
        project.bump_config_version()
    return project


# --- project members ----------------------------------------------------------------------


def add_member(project: Project, data: dict[str, Any]) -> ProjectMember:
    user = User.objects.filter(pk=data["user_id"]).first()
    if user is None or not Membership.objects.filter(org=project.org, user=user).exists():
        raise UnprocessableEntity(
            "The user must be a member of the organisation first",
            errors=[
                {
                    "field": "user_id",
                    "code": "not_in_org",
                    "message": "Invite them to the organisation",
                }
            ],
        )
    try:
        with transaction.atomic():
            row = ProjectMember.objects.create(
                org=project.org,
                project=project,
                user=user,
                role=data.get("role", "collector"),
                assigned_area=geojson_to_multipolygon(data.get("assigned_area"), "assigned_area"),
            )
    except IntegrityError as exc:
        raise Conflict("Already a member of this project") from exc
    _touch_membership(project.org, user)
    project.bump_config_version()
    return row


def update_member(project: Project, user_id: uuid.UUID, data: dict[str, Any]) -> ProjectMember:
    row = (
        ProjectMember.objects.select_related("user")
        .filter(project=project, user_id=user_id)
        .first()
    )
    if row is None:
        raise NotFound("Project member not found")
    if data.get("role") is not None:
        row.role = data["role"]
    if data.get("clear_assigned_area"):
        row.assigned_area = None
    elif data.get("assigned_area") is not None:
        row.assigned_area = geojson_to_multipolygon(data["assigned_area"], "assigned_area")
    row.version += 1
    row.save()
    _touch_membership(project.org, row.user)
    project.bump_config_version()
    return row


def remove_member(project: Project, user_id: uuid.UUID) -> None:
    row = (
        ProjectMember.objects.select_related("user")
        .filter(project=project, user_id=user_id)
        .first()
    )
    if row is None:
        raise NotFound("Project member not found")
    user = row.user
    row.delete()
    _touch_membership(project.org, user)
    project.bump_config_version()


def _touch_membership(org: Organisation, user: User) -> None:
    """Project assignments are part of the user's bundle ETag (Membership.version)."""
    m = Membership.objects.filter(org=org, user=user).first()
    if m is not None:
        m.bump_version()


# --- layers -------------------------------------------------------------------------------


def get_layer(layer_id: uuid.UUID) -> Layer:
    layer = Layer.objects.select_related("project").filter(pk=layer_id).first()
    if layer is None:
        raise NotFound("Layer not found")
    return layer


def create_layer(
    project: Project, data: dict[str, Any], *, draft_schema: dict[str, Any] | None = None
) -> Layer:
    from precisecapture.projects.schema_services import validate_profile_for_layer

    profile = data.get("capture_profile") or {}
    validate_profile_for_layer(project, data["geometry_type"], profile, extra_keys=[data["key"]])
    sort_order = data.get("sort_order")
    if sort_order is None:
        last = (
            Layer.objects.filter(project=project)
            .order_by("-sort_order")
            .values_list("sort_order", flat=True)
            .first()
        )
        sort_order = (last or 0) + 1
    try:
        with transaction.atomic():
            layer = Layer.objects.create(
                org=project.org,
                project=project,
                name=data["name"],
                key=data["key"],
                geometry_type=data["geometry_type"],
                style=data.get("style") or {},
                capture_profile=profile,
                draft_schema=draft_schema,
                sort_order=sort_order,
            )
    except IntegrityError as exc:
        raise Conflict(f"A layer with key '{data['key']}' already exists in this project") from exc
    project.bump_config_version()
    return layer


def update_layer(layer: Layer, data: dict[str, Any]) -> Layer:
    changed = False
    for key in ("name", "style", "sort_order"):
        if data.get(key) is not None and data[key] != getattr(layer, key):
            setattr(layer, key, data[key])
            changed = True
    if changed:
        layer.save()
        layer.project.bump_config_version()
    return layer


def delete_layer(layer: Layer) -> None:
    """Allowed only while the layer has no features (including soft-deleted ones)."""
    from precisecapture.features.models import Feature

    if Feature.all_tenants.filter(layer=layer).exists():
        raise Conflict(
            "The layer has features and cannot be deleted; archive the project instead "
            "(layer archiving arrives with the data views)"
        )
    project = layer.project
    layer.delete()
    project.bump_config_version()


def reorder_layers(project: Project, layer_ids: list[uuid.UUID]) -> list[Layer]:
    layers = {layer.id: layer for layer in Layer.objects.filter(project=project)}
    if set(layer_ids) != set(layers):
        raise UnprocessableEntity(
            "layer_ids must list every layer of the project exactly once",
            errors=[{"field": "layer_ids", "code": "mismatch", "message": "List every layer once"}],
        )
    with transaction.atomic():
        for position, layer_id in enumerate(layer_ids, start=1):
            Layer.objects.filter(pk=layer_id).update(sort_order=position)
    project.bump_config_version()
    return list(Layer.objects.filter(project=project))


def layer_keys(project: Project) -> list[str]:
    return list(Layer.objects.filter(project=project).values_list("key", flat=True))
