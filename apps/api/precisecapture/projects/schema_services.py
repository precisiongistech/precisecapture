"""
Layer schemas (draft → publish), capture profiles, templates and the bundle.

Publishing validates against the shared JSON Schema, parses every expression, checks key
uniqueness and relation targets, compares types with the previous version (safe widening
only), then writes an immutable LayerSchemaVersion and bumps the project's config_version.
"""

import hashlib
import uuid
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from precisecapture.accounts.models import User
from precisecapture.common.capture_profile import (
    resolve_capture_profile,
    validate_capture_profile_semantics,
)
from precisecapture.common.errors import Conflict, NotFound, UnprocessableEntity
from precisecapture.common.expr import ExpressionParseError, parse
from precisecapture.common.schema_validation import (
    SchemaIssue,
    validate_capture_profile,
    validate_layer_schema,
)
from precisecapture.orgs.models import Membership
from precisecapture.projects.models import Layer, LayerSchemaVersion, LayerTemplate, Project

# Type changes allowed between published versions: old -> set of new types.
SAFE_WIDENING: dict[str, set[str]] = {
    "integer": {"number", "decimal"},
    "decimal": {"number"},
    "number": {"decimal"},
    "select_one": {"select_many"},
    "phone": {"text"},
    "email": {"text"},
    "barcode": {"text"},
    "date": {"datetime"},
}

EXPRESSION_KEYS = ("relevant", "constraint", "expression")


def _issues_to_errors(issues: list[SchemaIssue]) -> list[dict[str, Any]]:
    return [i.as_dict() for i in issues]


# --- schema validation -------------------------------------------------------------------


def _walk_fields(
    fields: list[dict[str, Any]], prefix: str = "fields"
) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for i, field in enumerate(fields):
        path = f"{prefix}.{i}"
        out.append((path, field))
        if field.get("type") in ("repeat", "group") and isinstance(field.get("fields"), list):
            out.extend(_walk_fields(field["fields"], f"{path}.fields"))
    return out


def _field_types(schema: dict[str, Any]) -> dict[str, str]:
    """Flat key -> type map (repeat/group children keyed as parent.child)."""
    out: dict[str, str] = {}

    def walk(fields: list[dict[str, Any]], prefix: str) -> None:
        for f in fields:
            key = f"{prefix}{f['key']}"
            out[key] = str(f.get("type"))
            if f.get("type") in ("repeat", "group"):
                walk(f.get("fields") or [], f"{key}.")

    walk(schema.get("fields") or [], "")
    return out


def validate_schema_document(
    schema: dict[str, Any], *, layer_keys: list[str], previous: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """All problems with a schema document, as problem-JSON error entries."""
    errors = _issues_to_errors(validate_layer_schema(schema))
    if errors:
        return errors  # structural problems first; the rest assumes a well-formed document

    walked = _walk_fields(schema.get("fields") or [])
    top_keys = [f["key"] for f in schema.get("fields") or []]
    seen: set[str] = set()
    for path, field in walked:
        key = field["key"]
        scope_keys = top_keys
        if key in seen and path.count(".fields.") == 0:
            errors.append(
                {
                    "field": f"{path}.key",
                    "code": "duplicate",
                    "message": f"Key '{key}' is used twice",
                }
            )
        seen.add(key)
        for attr in EXPRESSION_KEYS:
            expr = field.get(attr)
            if isinstance(expr, str):
                try:
                    parse(expr, scope_keys + [k for k in _field_types(schema) if "." in k])
                except ExpressionParseError as exc:
                    errors.append(
                        {"field": f"{path}.{attr}", "code": "expression", "message": str(exc)}
                    )
        if isinstance(field.get("required"), str):
            try:
                parse(field["required"], scope_keys)
            except ExpressionParseError as exc:
                errors.append(
                    {"field": f"{path}.required", "code": "expression", "message": str(exc)}
                )
        if field.get("type") == "relation":
            target = (field.get("relation") or {}).get("layer")
            if target not in layer_keys:
                errors.append(
                    {
                        "field": f"{path}.relation.layer",
                        "code": "unknown_layer",
                        "message": f"No layer with key '{target}' in this project",
                    }
                )
        options = field.get("options")
        if isinstance(options, str) and options.startswith("list:"):
            name = options.removeprefix("list:")
            if name not in (schema.get("lists") or {}):
                errors.append(
                    {
                        "field": f"{path}.options",
                        "code": "unknown_list",
                        "message": f"No list named '{name}'",
                    }
                )
        parent = field.get("choiceFilterParent")
        if parent and parent not in top_keys:
            errors.append(
                {
                    "field": f"{path}.choiceFilterParent",
                    "code": "unknown_field",
                    "message": f"No field '{parent}'",
                }
            )

    if previous:
        old_types = _field_types(previous)
        new_types = _field_types(schema)
        for key, old in old_types.items():
            new = new_types.get(key)
            if new is None or new == old:
                continue
            if new not in SAFE_WIDENING.get(old, set()):
                errors.append(
                    {
                        "field": f"fields[{key}].type",
                        "code": "incompatible_type",
                        "message": (
                            f"'{key}' was {old} in version {previous.get('version')}; "
                            f"changing to {new} would break collected data"
                        ),
                    }
                )
    return errors


# --- draft / publish ----------------------------------------------------------------------


def current_schema(layer: Layer) -> LayerSchemaVersion | None:
    if layer.current_schema_version == 0:
        return None
    return LayerSchemaVersion.objects.filter(
        layer=layer, version=layer.current_schema_version
    ).first()


def save_draft(layer: Layer, attributes: dict[str, Any]) -> Layer:
    """Drafts only need to be structurally valid JSON; full checks happen at publish."""
    layer.draft_schema = attributes
    layer.save(update_fields=["draft_schema", "updated_at"])
    return layer


@transaction.atomic
def publish_schema(layer: Layer, user: User) -> tuple[LayerSchemaVersion, list[str]]:
    if not layer.draft_schema:
        raise Conflict("Nothing to publish: save a draft first")
    previous = current_schema(layer)
    doc = dict(layer.draft_schema)
    doc["schemaVersion"] = 1
    doc["layerId"] = layer.key
    doc["version"] = layer.current_schema_version + 1
    from precisecapture.projects.services import layer_keys

    errors = validate_schema_document(
        doc,
        layer_keys=layer_keys(layer.project),
        previous=previous.attributes if previous else None,
    )
    if errors:
        raise UnprocessableEntity("The schema has problems", errors=errors)
    if previous and _strip_version(previous.attributes) == _strip_version(doc):
        raise Conflict("The draft is identical to the current version")

    warnings: list[str] = []
    if previous:
        removed = set(_field_types(previous.attributes)) - set(_field_types(doc))
        if removed:
            warnings.append(f"Removed attributes stay in old data: {', '.join(sorted(removed))}")
        new_required = [
            f["key"]
            for _, f in _walk_fields(doc["fields"])
            if f.get("required") is True and f["key"] not in _field_types(previous.attributes)
        ]
        if new_required:
            warnings.append(
                f"New required attributes apply to new captures only: {', '.join(new_required)}"
            )

    try:
        version = LayerSchemaVersion.objects.create(
            org=layer.org, layer=layer, version=doc["version"], attributes=doc, published_by=user
        )
    except IntegrityError as exc:
        raise Conflict("Another publish happened at the same time; reload and try again") from exc
    layer.current_schema_version = version.version
    layer.draft_schema = None
    layer.save(update_fields=["current_schema_version", "draft_schema", "updated_at"])
    layer.project.bump_config_version()
    return version, warnings


def _strip_version(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in ("version", "layerId", "schemaVersion")}


# --- capture profiles ----------------------------------------------------------------------


def validate_profile_for_layer(
    project: Project,
    geometry_type: str,
    profile: dict[str, Any],
    *,
    extra_keys: list[str] | None = None,
) -> None:
    from precisecapture.projects.services import layer_keys

    issues = validate_capture_profile(profile)
    if not issues:
        keys = layer_keys(project) + (extra_keys or [])
        issues = validate_capture_profile_semantics(
            profile, geometry_type=geometry_type, layer_keys=keys
        )
    if issues:
        raise UnprocessableEntity(
            "The capture profile has problems", errors=_issues_to_errors(issues)
        )


def resolved_profile(layer: Layer) -> dict[str, Any]:
    return resolve_capture_profile(
        layer.org.capture_defaults, layer.project.capture_profile, layer.capture_profile, None
    )


def save_capture_profile(layer: Layer, profile: dict[str, Any]) -> Layer:
    validate_profile_for_layer(layer.project, layer.geometry_type, profile)
    if profile != layer.capture_profile:
        layer.capture_profile = profile
        layer.save(update_fields=["capture_profile", "updated_at"])
        layer.project.bump_config_version()
    return layer


# --- templates ------------------------------------------------------------------------------


def save_as_template(layer: Layer, user: User, name: str, description: str) -> LayerTemplate:
    schema = current_schema(layer)
    attributes = schema.attributes if schema else layer.draft_schema
    if not attributes:
        raise Conflict("The layer has no attributes to save")
    try:
        return LayerTemplate.objects.create(
            org=layer.org,
            name=name,
            description=description,
            geometry_type=layer.geometry_type,
            attributes=_strip_version(attributes),
            capture_profile=layer.capture_profile,
            style=layer.style,
            created_by=user,
        )
    except IntegrityError as exc:
        raise Conflict(f"A template named '{name}' already exists") from exc


def layer_from_template(project: Project, template_id: uuid.UUID, name: str, key: str) -> Layer:
    from precisecapture.projects.services import create_layer

    template = LayerTemplate.objects.filter(pk=template_id).first()
    if template is None:
        raise NotFound("Template not found")
    return create_layer(
        project,
        {
            "name": name,
            "key": key,
            "geometry_type": template.geometry_type,
            "style": template.style,
            "capture_profile": template.capture_profile,
        },
        draft_schema=template.attributes,
    )


# --- bundle -----------------------------------------------------------------------------------


def bundle_etag(
    project: Project, membership: Membership, project_member_version: int | None
) -> str:
    raw = (
        f"{project.id}:{project.config_version}:{membership.version}:"
        f"{project_member_version or 0}:{membership.role}"
    )
    return '"' + hashlib.sha256(raw.encode()).hexdigest()[:32] + '"'


def build_bundle(
    project: Project, membership: Membership, project_role: str | None
) -> dict[str, Any]:
    org = project.org
    layers_out: list[dict[str, Any]] = []
    for layer in Layer.objects.filter(project=project).order_by("sort_order", "id"):
        schema = current_schema(layer)
        layers_out.append(
            {
                "id": str(layer.id),
                "key": layer.key,
                "name": layer.name,
                "geometry_type": layer.geometry_type,
                "style": layer.style,
                "schema_version": layer.current_schema_version,
                "schema": schema.attributes if schema else None,
                "lists": (schema.attributes.get("lists") if schema else None) or {},
                "capture_profile": resolve_capture_profile(
                    org.capture_defaults, project.capture_profile, layer.capture_profile, None
                ),
                "sort_order": layer.sort_order,
            }
        )
    from precisecapture.projects.services import geom_to_geojson

    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "extent": geom_to_geojson(project.extent),
        },
        "org": {"id": str(org.id), "name": org.name},
        "my_role": project_role,
        "layers": layers_out,
        "basemap_packs": [],
        "config_version": project.config_version,
        "generated_at": timezone.now().isoformat(),
    }
