import json
import uuid
from typing import Any

from django.contrib.gis.geos import Polygon
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from ninja import Query, Router
from ninja.responses import Status

from precisecapture.common.auth import (
    current_device_id,
    current_membership,
    current_user,
    tenant_auth,
)
from precisecapture.common.errors import NotFound, UnprocessableEntity
from precisecapture.common.pagination import paginate
from precisecapture.common.permissions import require_project_role
from precisecapture.features import services, tiles
from precisecapture.features.models import Feature, FeatureHistory, FeatureRelation
from precisecapture.features.schemas import (
    FeatureCreateIn,
    FeatureDetailOut,
    FeatureListParams,
    FeatureOut,
    FeaturePatchIn,
    HistoryOut,
    ReviewIn,
)
from precisecapture.projects import services as project_services
from precisecapture.projects.models import Layer, Project
from precisecapture.projects.services import geom_to_geojson

layer_features_router = Router(tags=["features"], auth=tenant_auth)
features_router = Router(tags=["features"], auth=tenant_auth)
tiles_router = Router(tags=["tiles"], auth=tenant_auth)


# --- helpers ------------------------------------------------------------------------------


def _layer_for(request: HttpRequest, layer_id: uuid.UUID, minimum: str) -> Layer:
    layer = project_services.get_layer(layer_id)
    require_project_role(
        current_membership(request),
        project_services.project_member_role(layer.project, current_user(request)),
        minimum,
    )
    return layer


def _feature_for(request: HttpRequest, feature_id: uuid.UUID, minimum: str) -> Feature:
    feature = services.get_feature(feature_id)
    require_project_role(
        current_membership(request),
        project_services.project_member_role(feature.project, current_user(request)),
        minimum,
    )
    return feature


def _device(request: HttpRequest) -> Any:
    from precisecapture.accounts.models import Device

    device_id = current_device_id(request)
    return Device.objects.filter(pk=device_id).first() if device_id else None


def feature_out(f: Feature) -> dict[str, Any]:
    return {
        "id": f.id,
        "project_id": f.project_id,
        "layer_id": f.layer_id,
        "layer_key": f.layer.key,
        "geometry_type": f.geometry_type,
        "geom": geom_to_geojson(f.geom),
        "attributes": f.attributes,
        "schema_version": f.schema_version,
        "version": f.version,
        "status": f.status,
        "review_note": f.review_note,
        "reviewed_at": f.reviewed_at,
        "deleted": f.deleted,
        "computed": {
            "area_m2": f.area_m2,
            "area_ha": f.area_ha,
            "area_acres": f.area_acres,
            "perimeter_m": f.perimeter_m,
            "length_m": f.length_m,
            "centroid": geom_to_geojson(f.centroid),
            "centroid_method": f.centroid_method or None,
        },
        "qa_flags": f.qa_flags,
        "created_by": f.created_by_id,
        "updated_by": f.updated_by_id,
        "created_device": f.created_device_id,
        "updated_device": f.updated_device_id,
        "captured_at": f.captured_at,
        "created_at": f.created_at,
        "updated_at": f.updated_at,
    }


def _geojson_feature(f: Feature) -> dict[str, Any]:
    props = feature_out(f)
    geom = props.pop("geom")
    props.pop("id")
    return {"type": "Feature", "id": str(f.id), "geometry": geom, "properties": props}


def _parse_bbox(value: str | None) -> Polygon | None:
    if not value:
        return None
    try:
        parts = [float(p) for p in value.split(",")]
        if len(parts) != 4:
            raise ValueError
        minx, miny, maxx, maxy = parts
        if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
            raise ValueError
    except ValueError as exc:
        raise UnprocessableEntity(
            "bbox must be minLon,minLat,maxLon,maxLat",
            errors=[{"field": "bbox", "code": "invalid", "message": "minLon,minLat,maxLon,maxLat"}],
        ) from exc
    return Polygon.from_bbox((minx, miny, maxx, maxy))


def _filtered(layer: Layer, request: HttpRequest, params: FeatureListParams) -> QuerySet[Feature]:
    qs = Feature.objects.select_related("layer").filter(layer=layer)
    if not params.include_deleted:
        qs = qs.filter(deleted=False)
    if params.status:
        qs = qs.filter(status__in=[s.strip() for s in params.status.split(",") if s.strip()])
    if params.updated_since:
        qs = qs.filter(updated_at__gt=params.updated_since)
    if params.qa_flag:
        qs = qs.filter(qa_flags__contains=[params.qa_flag])
    bbox = _parse_bbox(params.bbox)
    if bbox is not None:
        qs = qs.filter(geom__bboverlaps=bbox)
    # attribute filters: ?attr.crop=cocoa  (exact match on the JSON value)
    for key, value in request.GET.items():
        if key.startswith("attr."):
            qs = qs.filter(**{f"attributes__{key[5:]}": value})
    return qs


# --- list / create under the layer --------------------------------------------------------


@layer_features_router.get("/{layer_id}/features", operation_id="listFeatures")
def list_features(
    request: HttpRequest, layer_id: uuid.UUID, params: Query[FeatureListParams]
) -> HttpResponse:
    """
    GeoJSON FeatureCollection of the layer's features. Filters: bbox, status, updated_since,
    include_deleted, qa_flag, attr.<key>=value. Cursor pagination: `next_cursor` and `has_more`
    are top-level members; UUIDv7 ids give creation order.
    """
    layer = _layer_for(request, layer_id, "viewer")
    page = paginate(_filtered(layer, request, params), cursor=params.cursor, limit=params.limit)
    body = {
        "type": "FeatureCollection",
        "features": [_geojson_feature(f) for f in page.items],
        "next_cursor": page.next_cursor,
        "has_more": page.has_more,
    }
    return HttpResponse(json.dumps(body, default=str), content_type="application/geo+json")


@layer_features_router.post(
    "/{layer_id}/features", response={201: FeatureOut}, operation_id="createFeature"
)
def create_feature(
    request: HttpRequest, layer_id: uuid.UUID, payload: FeatureCreateIn
) -> Status[dict[str, Any]]:
    """Create a feature from the web (collectors and managers); same write path as sync."""
    layer = _layer_for(request, layer_id, "collector")
    if payload.id is not None and Feature.objects.filter(pk=payload.id).exists():
        from precisecapture.common.errors import Conflict

        raise Conflict("A feature with this id already exists")
    result = services.write_feature(
        services.WriteRequest(
            layer=layer,
            user=current_user(request),
            device=_device(request),
            feature_id=payload.id,
            geom=payload.geom,
            attributes=payload.attributes,
            status=payload.status,
            schema_version=payload.schema_version,
            captured_at=payload.captured_at,
        )
    )
    return Status(201, feature_out(result.feature))


# --- single feature -----------------------------------------------------------------------


@features_router.get("/{feature_id}", response=FeatureDetailOut, operation_id="getFeature")
def get_feature(request: HttpRequest, feature_id: uuid.UUID) -> dict[str, Any]:
    """Feature with raw track, vertex metadata and relations (audit view)."""
    f = _feature_for(request, feature_id, "viewer")
    out = feature_out(f)
    track = getattr(f, "raw_track", None) if hasattr(f, "raw_track") else None
    try:
        track = f.raw_track
    except Exception:
        track = None
    out["raw_track"] = track.points if track else None
    out["vertex_meta"] = [
        {
            "i": v.vertex_index,
            "accuracy_m": v.accuracy_m,
            "fix_type": v.fix_type,
            "satellites": v.satellites,
            "t": v.timestamp,
            "source": v.source,
        }
        for v in f.vertex_meta.order_by("vertex_index")
    ]
    out["relations"] = {
        r.attribute_key: r.to_feature_id for r in FeatureRelation.objects.filter(from_feature=f)
    }
    return out


@features_router.get(
    "/{feature_id}/history", response=list[HistoryOut], operation_id="getFeatureHistory"
)
def get_history(request: HttpRequest, feature_id: uuid.UUID) -> list[dict[str, Any]]:
    f = _feature_for(request, feature_id, "viewer")
    return [
        {
            "version": h.version,
            "change_type": h.change_type,
            "changed_fields": h.changed_fields,
            "status": h.status,
            "review_note": h.review_note,
            "deleted": h.deleted,
            "geom": geom_to_geojson(h.geom),
            "attributes": h.attributes,
            "changed_by": h.changed_by_id,
            "device": h.device_id,
            "change_id": h.change_id,
            "changed_at": h.changed_at,
        }
        for h in FeatureHistory.objects.filter(feature=f).order_by("version")
    ]


@features_router.patch("/{feature_id}", response=FeatureOut, operation_id="updateFeature")
def update_feature(
    request: HttpRequest, feature_id: uuid.UUID, payload: FeaturePatchIn
) -> dict[str, Any]:
    """
    Web edit. Send `base_version` (or `If-Match: "<version>"`); a stale version gives 409.
    Omitted keys keep their values; `attributes` replaces the whole attribute set.
    """
    f = _feature_for(request, feature_id, "collector")
    base = payload.base_version
    if base is None:
        if_match = request.headers.get("If-Match", "").strip().strip('"')
        base = int(if_match) if if_match.isdigit() else None
    data = payload.dict(exclude_unset=True)
    result = services.write_feature(
        services.WriteRequest(
            layer=f.layer,
            user=current_user(request),
            device=_device(request),
            feature_id=f.id,
            geom=data.get("geom"),
            geom_given="geom" in data,
            attributes=data.get("attributes"),
            attributes_given="attributes" in data,
            status=payload.status,
            base_version=base,
        )
    )
    return feature_out(result.feature)


@features_router.delete("/{feature_id}", response={204: None}, operation_id="deleteFeature")
def delete_feature(request: HttpRequest, feature_id: uuid.UUID) -> Status[None]:
    """Soft delete (so it syncs). Restore with POST /features/{id}/restore."""
    f = _feature_for(request, feature_id, "collector")
    services.delete_feature(f, current_user(request), _device(request))
    return Status(204, None)


@features_router.post("/{feature_id}/restore", response=FeatureOut, operation_id="restoreFeature")
def restore_feature(request: HttpRequest, feature_id: uuid.UUID) -> dict[str, Any]:
    f = _feature_for(request, feature_id, "manager")
    return feature_out(services.restore_feature(f, current_user(request)))


@features_router.post("/{feature_id}/review", response=FeatureOut, operation_id="reviewFeature")
def review_feature(
    request: HttpRequest, feature_id: uuid.UUID, payload: ReviewIn
) -> dict[str, Any]:
    """Approve, reject, or send back with a note (the collector sees it on the next pull)."""
    f = _feature_for(request, feature_id, "manager")
    return feature_out(
        services.review_feature(f, current_user(request), payload.action, payload.note)
    )


# --- tiles --------------------------------------------------------------------------------


@tiles_router.get("/{project_id}/tiles/{layer_id}/{z}/{x}/{y}.mvt", operation_id="getLayerTile")
def get_tile(
    request: HttpRequest, project_id: uuid.UUID, layer_id: uuid.UUID, z: int, x: int, y: int
) -> HttpResponse:
    """Mapbox vector tile for one layer, proxied from internal Martin after membership checks."""
    project = project_services.get_project(project_id)
    require_project_role(
        current_membership(request),
        project_services.project_member_role(project, current_user(request)),
        "viewer",
    )
    if not Layer.objects.filter(pk=layer_id, project=project).exists():
        raise NotFound("Layer not found in this project")
    if not (0 <= z <= 22 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise NotFound("Tile out of range")
    status, body, content_type = tiles.fetch_tile(
        tiles.martin_tile_url(project.id, layer_id, z, x, y)
    )
    resp = HttpResponse(body, status=status, content_type=content_type)
    if status == 200:
        resp["Cache-Control"] = "private, max-age=30"
    return resp


_ = Project
