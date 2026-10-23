"""
The single write path for features (web and sync): validate attributes against the schema
version, validate geometry against the capture profile, compute derived fields, run overlap
QA, write the row, its history and relations in one transaction.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from django.contrib.gis.geos import GEOSGeometry
from django.db import transaction
from django.utils import timezone

from precisecapture.accounts.models import Device, User
from precisecapture.common.errors import Conflict, NotFound, UnprocessableEntity
from precisecapture.common.schema_validation import SchemaIssue
from precisecapture.features import geometry as geo
from precisecapture.features import qa
from precisecapture.features.models import (
    ChangeType,
    Feature,
    FeatureHistory,
    FeatureRelation,
    FeatureStatus,
    RawTrack,
    VertexMeta,
)
from precisecapture.features.validation import AttributeContext, validate_attributes
from precisecapture.projects.models import Layer, LayerSchemaVersion, ProjectMember
from precisecapture.projects.schema_services import resolved_profile


@dataclass
class WriteRequest:
    """Everything a create/update needs. `geom` is GeoJSON (dict) or None; omit keys to keep."""

    layer: Layer
    user: User | None
    device: Device | None = None
    feature_id: uuid.UUID | None = None  # client id on create; required on update
    geom: dict[str, Any] | None = None
    geom_given: bool = True
    attributes: dict[str, Any] | None = None
    attributes_given: bool = True
    status: str | None = None
    schema_version: int | None = None
    base_version: int | None = None  # optimistic concurrency: must equal the current version
    captured_at: Any = None
    change_id: uuid.UUID | None = None
    changed_fields: list[str] | None = None
    raw_track: list[list[float]] | None = None
    vertex_meta: list[dict[str, Any]] | None = None


@dataclass
class WriteResult:
    feature: Feature
    created: bool
    history: FeatureHistory
    qa_flags: list[str] = field(default_factory=list)


class FeatureValidationError(UnprocessableEntity):
    pass


class StaleVersion(Conflict):
    slug = "stale-version"
    title = "Stale version"


def _schema_doc(layer: Layer, version: int | None) -> tuple[int, dict[str, Any]]:
    v = version or layer.current_schema_version
    if v == 0:
        raise FeatureValidationError(
            "The layer has no published schema",
            errors=[
                {
                    "field": "schema_version",
                    "code": "unpublished",
                    "message": "Publish the layer first",
                }
            ],
        )
    row = LayerSchemaVersion.objects.filter(layer=layer, version=v).first()
    if row is None:
        raise FeatureValidationError(
            f"Unknown schema version {v}",
            errors=[
                {
                    "field": "schema_version",
                    "code": "unknown",
                    "message": f"Layer has no version {v}",
                }
            ],
        )
    return v, row.attributes


def _issues(issues: list[SchemaIssue]) -> list[dict[str, Any]]:
    return [i.as_dict() for i in issues]


def get_feature(feature_id: uuid.UUID, *, include_deleted: bool = True) -> Feature:
    qs = Feature.objects.select_related("layer", "project")
    if not include_deleted:
        qs = qs.filter(deleted=False)
    feature = qs.filter(pk=feature_id).first()
    if feature is None:
        raise NotFound("Feature not found")
    return feature


@transaction.atomic
def write_feature(req: WriteRequest) -> WriteResult:
    layer = req.layer
    existing: Feature | None = None
    if req.feature_id is not None:
        existing = Feature.objects.select_for_update().filter(pk=req.feature_id).first()
    if existing is not None and existing.layer_id != layer.id:
        raise Conflict("The feature belongs to another layer")
    if (
        existing is not None
        and req.base_version is not None
        and existing.version != req.base_version
    ):
        raise StaleVersion(
            f"The feature is at version {existing.version}, you edited version {req.base_version}"
        )

    schema_version, schema_doc = _schema_doc(
        layer, req.schema_version or (existing.schema_version if existing else None)
    )
    profile = resolved_profile(layer)
    errors: list[dict[str, Any]] = []

    # --- geometry ------------------------------------------------------------------
    if req.geom_given:
        try:
            geom = geo.parse_geometry(req.geom)
        except ValueError as exc:
            raise FeatureValidationError(
                str(exc), errors=[{"field": "geom", "code": "invalid", "message": str(exc)}]
            ) from exc
    else:
        geom = existing.geom if existing else None
    type_issue = geo.check_type(layer.geometry_type, geom)
    if type_issue:
        errors.append(type_issue.as_dict())
    measures = geo.measure(geom) if not type_issue else geo.Measures()
    geom_issues, geom_flags = geo.validate_against_profile(
        layer.geometry_type, geom, measures, profile
    )
    errors.extend(_issues(geom_issues))

    # --- attributes ------------------------------------------------------------------
    incoming = (
        req.attributes if req.attributes_given else (dict(existing.attributes) if existing else {})
    )
    if existing is not None and req.attributes_given and req.changed_fields:
        # Partial update from sync: fields not listed keep their stored values.
        merged = dict(existing.attributes)
        for key in req.changed_fields:
            if key == "geom":
                continue
            if key in (req.attributes or {}):
                merged[key] = (req.attributes or {})[key]
            else:
                merged.pop(key, None)
        incoming = merged
    ctx = AttributeContext(
        now=timezone.now(),
        geom_area_m2=measures.area_m2,
        geom_length_m=measures.length_m if measures.length_m is not None else measures.perimeter_m,
        previous=existing.attributes if existing else None,
    )
    result = validate_attributes(schema_doc, incoming, context=ctx)
    errors.extend(_issues(result.errors))

    # --- relations and uniqueness (need the DB) ---------------------------------------------
    relation_targets: dict[str, Feature] = {}
    for key, target_layer_key, target_id in result.relation_refs:
        target = Feature.objects.filter(
            pk=target_id, layer__key=target_layer_key, project=layer.project, deleted=False
        ).first()
        if target is None:
            errors.append(
                {
                    "field": key,
                    "code": "unknown_relation",
                    "message": f"No feature {target_id} in layer {target_layer_key}",
                }
            )
        else:
            relation_targets[key] = target
    for key, value in result.unique_checks:
        clash = Feature.objects.filter(layer=layer, deleted=False, **{f"attributes__{key}": value})
        if existing is not None:
            clash = clash.exclude(pk=existing.pk)
        if clash.exists():
            errors.append(
                {
                    "field": key,
                    "code": "unique",
                    "message": f"'{value}' is already used by another feature",
                }
            )

    if errors:
        raise FeatureValidationError("The feature has problems", errors=errors)

    # --- QA (flags only, or block per profile) ------------------------------------------------
    overlap_issues, overlap_flags, _ = qa.check_overlaps(
        layer_id=layer.id,
        org_id=layer.org_id,
        geom=geom,
        exclude_feature_id=existing.pk if existing else req.feature_id,
        profile=profile,
    )
    if overlap_issues:
        raise FeatureValidationError("The feature has problems", errors=_issues(overlap_issues))
    assigned_area = None
    if req.user is not None:
        pm = (
            ProjectMember.objects.filter(project=layer.project, user=req.user)
            .only("assigned_area")
            .first()
        )
        assigned_area = pm.assigned_area if pm else None
    flags = sorted(
        set(
            measures.qa_flags
            + geom_flags
            + overlap_flags
            + geo.extent_flags(geom, layer.project.extent, assigned_area)
        )
    )

    # --- write ----------------------------------------------------------------------------------
    now = timezone.now()
    status = req.status or (existing.status if existing else FeatureStatus.SUBMITTED)
    if existing is None:
        feature = Feature(
            id=req.feature_id or uuid.uuid4(),
            org=layer.org,
            project=layer.project,
            layer=layer,
            geometry_type=layer.geometry_type,
            created_by=req.user,
            created_device=req.device,
            captured_at=req.captured_at,
            schema_version=schema_version,
            version=1,
        )
        change_type = ChangeType.CREATE
        changed = sorted(set(["geom"] if geom is not None else []) | set(result.values))
    else:
        feature = existing
        feature.version += 1
        change_type = ChangeType.UPDATE
        changed = req.changed_fields or _diff(existing, geom, result.values, status)
        if existing.deleted:
            change_type = ChangeType.RESTORE
            feature.deleted = False
            feature.deleted_at = None
    feature.geom = geom
    feature.attributes = result.values
    feature.schema_version = schema_version
    feature.status = status
    feature.updated_by = req.user
    feature.updated_device = req.device
    feature.area_m2, feature.perimeter_m, feature.length_m = (
        measures.area_m2,
        measures.perimeter_m,
        measures.length_m,
    )
    feature.centroid = measures.centroid  # type: ignore[assignment]
    feature.centroid_method = measures.centroid_method
    feature.qa_flags = flags
    feature.save()

    history = _record_history(feature, change_type, changed, req)
    _sync_relations(feature, relation_targets)
    if req.raw_track is not None:
        RawTrack.objects.update_or_create(
            feature=feature,
            defaults={
                "org": feature.org,
                "points": req.raw_track,
                "point_count": len(req.raw_track),
            },
        )
    if req.vertex_meta is not None:
        VertexMeta.objects.filter(feature=feature).delete()
        VertexMeta.objects.bulk_create(
            [
                VertexMeta(
                    org=feature.org,
                    feature=feature,
                    vertex_index=int(v.get("i", i)),
                    accuracy_m=v.get("accuracy_m"),
                    fix_type=v.get("fix_type") or "",
                    satellites=v.get("satellites"),
                    timestamp=v.get("t"),
                    source=v.get("source") or "",
                )
                for i, v in enumerate(req.vertex_meta)
            ]
        )
    _ = now
    return WriteResult(feature=feature, created=existing is None, history=history, qa_flags=flags)


def _diff(
    existing: Feature, geom: GEOSGeometry | None, attributes: dict[str, Any], status: str
) -> list[str]:
    changed: set[str] = set()
    old_geom = existing.geom
    if (old_geom is None) != (geom is None) or (
        old_geom is not None and geom is not None and not old_geom.equals_exact(geom, 1e-9)
    ):
        changed.add("geom")
    for key in set(existing.attributes) | set(attributes):
        if existing.attributes.get(key) != attributes.get(key):
            changed.add(key)
    if status != existing.status:
        changed.add("status")
    return sorted(changed)


def _record_history(
    feature: Feature, change_type: str, changed: list[str], req: WriteRequest
) -> FeatureHistory:
    return FeatureHistory.objects.create(
        org=feature.org,
        feature=feature,
        version=feature.version,
        change_type=change_type,
        geom=feature.geom,
        attributes=feature.attributes,
        status=feature.status,
        review_note=feature.review_note,
        deleted=feature.deleted,
        changed_fields=changed,
        changed_by=req.user,
        device=req.device,
        change_id=req.change_id,
    )


def _sync_relations(feature: Feature, targets: dict[str, Feature]) -> None:
    FeatureRelation.objects.filter(from_feature=feature).exclude(
        attribute_key__in=list(targets)
    ).delete()
    for key, target in targets.items():
        FeatureRelation.objects.update_or_create(
            from_feature=feature,
            attribute_key=key,
            defaults={"org": feature.org, "to_feature": target},
        )


# --- delete / restore / review ----------------------------------------------------------------


@transaction.atomic
def delete_feature(
    feature: Feature,
    user: User | None,
    device: Device | None = None,
    change_id: uuid.UUID | None = None,
) -> Feature:
    feature = Feature.objects.select_for_update().get(pk=feature.pk)
    if feature.deleted:
        return feature
    feature.deleted = True
    feature.deleted_at = timezone.now()
    feature.version += 1
    feature.updated_by = user
    feature.updated_device = device
    feature.save()
    _record_history(
        feature,
        ChangeType.DELETE,
        ["deleted"],
        WriteRequest(layer=feature.layer, user=user, device=device, change_id=change_id),
    )
    return feature


@transaction.atomic
def restore_feature(feature: Feature, user: User | None) -> Feature:
    feature = Feature.objects.select_for_update().get(pk=feature.pk)
    if not feature.deleted:
        return feature
    feature.deleted = False
    feature.deleted_at = None
    feature.version += 1
    feature.updated_by = user
    feature.save()
    _record_history(
        feature, ChangeType.RESTORE, ["deleted"], WriteRequest(layer=feature.layer, user=user)
    )
    return feature


REVIEW_ACTIONS: dict[str, str] = {
    "approve": FeatureStatus.APPROVED,
    "reject": FeatureStatus.REJECTED,
    "send_back": FeatureStatus.SENT_BACK,
}


@transaction.atomic
def review_feature(feature: Feature, user: User, action: str, note: str = "") -> Feature:
    """Managers approve, reject or send back (with a note the collector sees on the next pull)."""
    if action not in REVIEW_ACTIONS:
        raise UnprocessableEntity(
            "Unknown review action",
            errors=[
                {"field": "action", "code": "invalid", "message": "approve | reject | send_back"}
            ],
        )
    if action == "send_back" and not note.strip():
        raise UnprocessableEntity(
            "A note is required when sending back",
            errors=[
                {"field": "note", "code": "required", "message": "Tell the collector what to fix"}
            ],
        )
    feature = Feature.objects.select_for_update().get(pk=feature.pk)
    if feature.deleted:
        raise Conflict("Cannot review a deleted feature")
    feature.status = REVIEW_ACTIONS[action]
    feature.review_note = note.strip()
    feature.reviewed_by = user
    feature.reviewed_at = timezone.now()
    feature.version += 1
    feature.updated_by = user
    feature.save()
    _record_history(
        feature,
        ChangeType.REVIEW,
        ["status", "review_note"],
        WriteRequest(layer=feature.layer, user=user),
    )
    return feature
