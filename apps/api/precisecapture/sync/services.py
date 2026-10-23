"""
Push, pull and conflict resolution (ENGINEERING_NOTES.md §2).

Push: one transaction per project with ProjectSyncState locked FOR UPDATE; each change is
applied in its own savepoint through features.services.write_feature(), which appends the
changelog row with the next seq. Idempotent on change_id via AppliedChange.
"""

import time
import uuid
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from precisecapture.accounts.models import Device, User
from precisecapture.common.errors import Conflict as ConflictError
from precisecapture.common.errors import NotFound, UnprocessableEntity
from precisecapture.features import services as feature_services
from precisecapture.features.models import ChangeType, Feature, FeatureHistory
from precisecapture.features.services import FeatureValidationError, WriteRequest
from precisecapture.projects.models import Layer, Project
from precisecapture.projects.services import geom_to_geojson
from precisecapture.sync import changelog
from precisecapture.sync.models import (
    AppliedChange,
    ChangeLog,
    Conflict,
    ProjectSyncState,
    SyncCursor,
)

MAX_CHANGES = 200
CONFLICT_FLAG = "conflict"
NON_CONFLICTING_FIELDS = {"status", "review_note"}


@dataclass
class PushOutcome:
    results: list[dict[str, Any]]
    last_seq: int
    config_version: int


# --- helpers --------------------------------------------------------------------------------


def _result(change: dict[str, Any], status: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"change_id": str(change["change_id"]), "status": status}
    out.update(extra)
    return out


def _feature_ref(feature: Feature) -> dict[str, Any]:
    return {"id": str(feature.id), "version": feature.version}


def _server_changed_fields_since(feature: Feature, base_version: int) -> set[str]:
    rows = FeatureHistory.objects.filter(feature=feature, version__gt=base_version).values_list(
        "changed_fields", flat=True
    )
    out: set[str] = set()
    for fields in rows:
        out.update(fields or [])
    return out - NON_CONFLICTING_FIELDS


def _payload_of(feature: Feature) -> dict[str, Any]:
    return {
        "geom": geom_to_geojson(feature.geom),
        "attributes": feature.attributes,
        "status": feature.status,
        "deleted": feature.deleted,
        "version": feature.version,
    }


def _same_payload(feature: Feature, change: dict[str, Any]) -> bool:
    return (change.get("geom") or None) == (geom_to_geojson(feature.geom) or None) and (
        change.get("attributes") or {}
    ) == feature.attributes


def _open_conflict(
    *,
    feature: Feature,
    change: dict[str, Any],
    reason: str,
    overlapping: list[str],
    device: Device | None,
    user: User | None,
) -> Conflict:
    conflict = Conflict.objects.create(
        org=feature.org,
        feature=feature,
        project=feature.project,
        device=device,
        user=user,
        change_id=change["change_id"],
        reason=reason,
        base_version=change.get("base_version"),
        server_version=feature.version,
        local_payload={
            k: change.get(k)
            for k in ("op", "geom", "attributes", "changed_fields", "status", "meta")
        },
        server_payload=_payload_of(feature),
        overlapping_fields=overlapping,
    )
    if CONFLICT_FLAG not in feature.qa_flags:
        feature.qa_flags = [*feature.qa_flags, CONFLICT_FLAG]
        feature.save(update_fields=["qa_flags", "updated_at"])
    return conflict


# --- push -------------------------------------------------------------------------------------


def push(
    project: Project, user: User, device: Device | None, changes: list[dict[str, Any]]
) -> PushOutcome:
    if len(changes) > MAX_CHANGES:
        raise UnprocessableEntity(
            f"At most {MAX_CHANGES} changes per push",
            errors=[
                {"field": "changes", "code": "too_many", "message": f"Send at most {MAX_CHANGES}"}
            ],
        )
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    rejected = conflicts = 0
    with transaction.atomic():
        state = changelog.lock_project_state(project.id, project.org_id)
        layers = {layer.id: layer for layer in Layer.objects.filter(project=project)}
        for change in changes:
            for key in ("change_id", "id", "layer_id"):  # callers may pass strings
                change[key] = uuid.UUID(str(change[key]))
            applied = AppliedChange.objects.filter(change_id=change["change_id"]).first()
            if applied is not None:
                results.append(
                    {**applied.result, "change_id": str(change["change_id"]), "status": "duplicate"}
                )
                continue
            try:
                with transaction.atomic():  # savepoint: a rejection must not poison the batch
                    result = _apply(change, layers, user, device, state)
            except FeatureValidationError as exc:
                result = _result(change, "rejected", errors=exc.errors)
            except ConflictError as exc:
                result = _result(
                    change,
                    "rejected",
                    errors=[{"field": None, "code": exc.slug, "message": exc.detail or exc.title}],
                )
            if result["status"] == "rejected":
                rejected += 1
            elif result["status"] == "conflict":
                conflicts += 1
            AppliedChange.objects.create(
                org=project.org,
                project=project,
                device=device,
                change_id=change["change_id"],
                result=result,
                seq=state.last_seq,
            )
            results.append(result)
        state.refresh_from_db(fields=["last_seq"])
        last_seq = state.last_seq
        project.refresh_from_db(fields=["config_version"])
        _touch_cursor(
            device,
            project,
            push=True,
            pushed=len(changes),
            rejected=rejected,
            conflicts=conflicts,
            ms=int((time.perf_counter() - started) * 1000),
        )
    return PushOutcome(results=results, last_seq=last_seq, config_version=project.config_version)


def _apply(
    change: dict[str, Any],
    layers: dict[uuid.UUID, Layer],
    user: User,
    device: Device | None,
    state: ProjectSyncState,
) -> dict[str, Any]:
    layer = layers.get(change["layer_id"])
    if layer is None:
        raise FeatureValidationError(
            "Unknown layer",
            errors=[
                {
                    "field": "layer_id",
                    "code": "unknown_layer",
                    "message": "Not a layer of this project",
                }
            ],
        )
    op = change["op"]
    meta = change.get("meta") or {}
    feature = Feature.objects.select_for_update().filter(pk=change["id"]).first()
    base_version = change.get("base_version")
    common: dict[str, Any] = {
        "layer": layer,
        "user": user,
        "device": device,
        "feature_id": change["id"],
        "schema_version": change.get("schema_version"),
        "captured_at": meta.get("captured_at"),
        "change_id": change["change_id"],
        "raw_track": meta.get("raw_track"),
        "vertex_meta": meta.get("vertex_meta"),
    }

    if op == "create":
        if feature is not None:
            if _same_payload(feature, change):
                return _result(change, "duplicate", feature=_feature_ref(feature))
            raise FeatureValidationError(
                "A different feature with this id already exists",
                errors=[
                    {
                        "field": "id",
                        "code": "exists",
                        "message": "Id already used by another feature",
                    }
                ],
            )
        result = feature_services.write_feature(
            WriteRequest(
                **common,
                geom=change.get("geom"),
                attributes=change.get("attributes") or {},
                status=change.get("status"),
            )
        )
        return _result(change, "accepted", feature=_feature_ref(result.feature))

    if feature is None:
        raise FeatureValidationError(
            "Unknown feature",
            errors=[
                {
                    "field": "id",
                    "code": "not_found",
                    "message": "No feature with this id; use op=create",
                }
            ],
        )
    if feature.layer_id != layer.id:
        raise FeatureValidationError(
            "Wrong layer",
            errors=[
                {
                    "field": "layer_id",
                    "code": "mismatch",
                    "message": "Feature belongs to another layer",
                }
            ],
        )

    if op == "delete":
        if feature.deleted:
            return _result(change, "duplicate", feature=_feature_ref(feature))
        if base_version is not None and feature.version > base_version:
            conflict = _open_conflict(
                feature=feature,
                change=change,
                reason="delete_vs_edit",
                overlapping=[],
                device=device,
                user=user,
            )
            return _result(
                change, "conflict", feature=_feature_ref(feature), conflict_id=str(conflict.id)
            )
        feature_services.delete_feature(feature, user, device, change_id=change["change_id"])
        feature.refresh_from_db()
        return _result(change, "accepted", feature=_feature_ref(feature))

    # update
    if feature.deleted:
        conflict = _open_conflict(
            feature=feature,
            change=change,
            reason="edit_vs_delete",
            overlapping=[],
            device=device,
            user=user,
        )
        return _result(
            change, "conflict", feature=_feature_ref(feature), conflict_id=str(conflict.id)
        )
    local_fields = set(change.get("changed_fields") or [])
    if base_version is None or base_version == feature.version:
        status = "accepted"
    elif base_version > feature.version:
        raise FeatureValidationError(
            "base_version is ahead of the server",
            errors=[
                {
                    "field": "base_version",
                    "code": "invalid",
                    "message": f"Server is at {feature.version}",
                }
            ],
        )
    else:
        server_fields = _server_changed_fields_since(feature, base_version)
        overlap = sorted(local_fields & server_fields)
        if overlap:
            conflict = _open_conflict(
                feature=feature,
                change=change,
                reason="field_overlap",
                overlapping=overlap,
                device=device,
                user=user,
            )
            return _result(
                change, "conflict", feature=_feature_ref(feature), conflict_id=str(conflict.id)
            )
        status = "merged"
    geom_given = "geom" in local_fields or (status == "accepted" and "geom" in change)
    result = feature_services.write_feature(
        WriteRequest(
            **common,
            geom=change.get("geom"),
            geom_given=geom_given,
            attributes=change.get("attributes") or {},
            attributes_given=True,
            changed_fields=sorted(local_fields) if local_fields else None,
            status=change.get("status"),
            base_version=feature.version,  # reconciled above
        )
    )
    return _result(change, status, feature=_feature_ref(result.feature))


# --- pull --------------------------------------------------------------------------------------


def pull(project: Project, device: Device | None, cursor: int, limit: int) -> dict[str, Any]:
    started = time.perf_counter()
    rows = list(
        ChangeLog.objects.filter(project=project, seq__gt=cursor).order_by("seq")[: limit + 1]
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1].seq if rows else cursor
    latest_seq: dict[uuid.UUID, int] = {}
    for row in rows:  # collapse: latest state once per feature
        latest_seq[row.entity_id] = row.seq
    features = {
        f.id: f for f in Feature.objects.select_related("layer").filter(pk__in=list(latest_seq))
    }
    items = [
        _pull_item(features[fid], seq)
        for fid, seq in sorted(latest_seq.items(), key=lambda kv: kv[1])
        if fid in features
    ]
    project.refresh_from_db(fields=["config_version"])
    _touch_cursor(
        device,
        project,
        push=False,
        pulled=len(items),
        cursor=next_cursor,
        ms=int((time.perf_counter() - started) * 1000),
    )
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "config_version": project.config_version,
    }


def _pull_item(f: Feature, seq: int) -> dict[str, Any]:
    return {
        "seq": seq,
        "entity": "feature",
        "id": str(f.id),
        "layer_id": str(f.layer_id),
        "version": f.version,
        "deleted": f.deleted,
        "schema_version": f.schema_version,
        "geom": None if f.deleted else geom_to_geojson(f.geom),
        "attributes": {} if f.deleted else f.attributes,
        "status": f.status,
        "review_note": f.review_note or None,
        "computed": {
            "area_m2": f.area_m2,
            "length_m": f.length_m if f.length_m is not None else f.perimeter_m,
            "centroid": geom_to_geojson(f.centroid),
            "centroid_method": f.centroid_method or None,
        },
        "qa_flags": f.qa_flags,
        "updated_at": f.updated_at.isoformat(),
        "updated_by": str(f.updated_by_id) if f.updated_by_id else None,
    }


def _touch_cursor(device: Device | None, project: Project, *, push: bool, **metrics: Any) -> None:
    if device is None:
        return
    now = timezone.now()
    cursor, _ = SyncCursor.objects.get_or_create(
        device=device, project=project, defaults={"org": project.org}
    )
    if push:
        cursor.last_push_at = now
        cursor.pushed_changes += metrics.get("pushed", 0)
        cursor.rejected_changes += metrics.get("rejected", 0)
        cursor.conflicts += metrics.get("conflicts", 0)
        cursor.last_push_ms = metrics.get("ms")
    else:
        cursor.last_pull_at = now
        cursor.pulled_items += metrics.get("pulled", 0)
        cursor.last_pulled_seq = max(cursor.last_pulled_seq, metrics.get("cursor", 0))
        cursor.last_pull_ms = metrics.get("ms")
    cursor.save()
    device.last_sync_at = now
    device.save(update_fields=["last_sync_at", "updated_at"])


# --- conflicts ------------------------------------------------------------------------------------


def get_conflict(conflict_id: uuid.UUID) -> Conflict:
    conflict = (
        Conflict.objects.select_related("feature", "feature__layer", "project")
        .filter(pk=conflict_id)
        .first()
    )
    if conflict is None:
        raise NotFound("Conflict not found")
    return conflict


@transaction.atomic
def resolve_conflict(
    conflict: Conflict, user: User, resolution: str, merged: dict[str, Any] | None
) -> Conflict:
    if conflict.status == Conflict.Status.RESOLVED:
        raise ConflictError("Already resolved")
    feature = (
        Feature.objects.select_for_update()
        .select_related("layer", "project")
        .get(pk=conflict.feature_id)
    )
    payload: dict[str, Any] | None
    if resolution == Conflict.Resolution.KEEP_SERVER:
        payload = None
    elif resolution == Conflict.Resolution.KEEP_DEVICE:
        local = conflict.local_payload
        if local.get("op") == "delete":
            feature_services.delete_feature(feature, user)
            payload = None
        else:
            payload = {
                "geom": local.get("geom"),
                "attributes": local.get("attributes") or {},
                "status": local.get("status"),
            }
    elif resolution == Conflict.Resolution.MERGED:
        if not merged:
            raise UnprocessableEntity(
                "A merged payload is required",
                errors=[
                    {"field": "merged", "code": "required", "message": "Send geom and attributes"}
                ],
            )
        payload = {
            "geom": merged.get("geom"),
            "attributes": merged.get("attributes") or {},
            "status": merged.get("status"),
        }
    else:
        raise UnprocessableEntity(
            "Unknown resolution",
            errors=[
                {
                    "field": "resolution",
                    "code": "invalid",
                    "message": "keep_server | keep_device | merged",
                }
            ],
        )

    if payload is not None:
        if feature.deleted:
            feature_services.restore_feature(feature, user)
            feature.refresh_from_db()
        result = feature_services.write_feature(
            WriteRequest(
                layer=feature.layer,
                user=user,
                feature_id=feature.id,
                geom=payload["geom"],
                geom_given=payload["geom"] is not None or feature.layer.geometry_type == "none",
                attributes=payload["attributes"],
                status=payload.get("status") or feature.status,
            )
        )
        feature = result.feature
        result.history.change_type = ChangeType.MERGE
        result.history.save(update_fields=["change_type"])
    feature.refresh_from_db()
    other_open = (
        Conflict.objects.filter(feature=feature, status=Conflict.Status.OPEN)
        .exclude(pk=conflict.pk)
        .exists()
    )
    if CONFLICT_FLAG in feature.qa_flags and not other_open:
        feature.qa_flags = [f for f in feature.qa_flags if f != CONFLICT_FLAG]
        feature.save(update_fields=["qa_flags", "updated_at"])
        if payload is None:
            changelog.record(
                feature, "update", user_id=user.id
            )  # devices must learn the flag is gone
    conflict.status = Conflict.Status.RESOLVED
    conflict.resolution = resolution
    conflict.resolved_by = user
    conflict.resolved_at = timezone.now()
    conflict.save()
    return conflict
