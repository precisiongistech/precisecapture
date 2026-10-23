import uuid
from typing import Any

from django.http import HttpRequest, HttpResponse
from ninja import Router
from ninja.responses import Status

from precisecapture.common.auth import current_membership, current_user, tenant_auth
from precisecapture.common.permissions import require_project_role
from precisecapture.projects import schema_services, services
from precisecapture.projects.models import (
    Layer,
    LayerSchemaVersion,
    LayerTemplate,
    Project,
    ProjectMember,
)
from precisecapture.projects.schemas import (
    CaptureProfileIn,
    CaptureProfileOut,
    LayerFromTemplateIn,
    LayerIn,
    LayerOut,
    LayerPatchIn,
    LayerReorderIn,
    ProjectIn,
    ProjectMemberIn,
    ProjectMemberOut,
    ProjectMemberPatchIn,
    ProjectOut,
    ProjectPatchIn,
    SchemaDraftIn,
    SchemaOut,
    SchemaPublishOut,
    SchemaVersionOut,
    TemplateIn,
    TemplateOut,
)

projects_router = Router(tags=["projects"], auth=tenant_auth)
layers_router = Router(tags=["layers"], auth=tenant_auth)
templates_router = Router(tags=["layers"], auth=tenant_auth)


# --- helpers ---------------------------------------------------------------------------


def _project_for(request: HttpRequest, project_id: uuid.UUID, minimum: str) -> tuple[Project, str]:
    project = services.get_project(project_id)
    role = require_project_role(
        current_membership(request),
        services.project_member_role(project, current_user(request)),
        minimum,
    )
    return project, role


def _layer_for(request: HttpRequest, layer_id: uuid.UUID, minimum: str) -> Layer:
    layer = services.get_layer(layer_id)
    require_project_role(
        current_membership(request),
        services.project_member_role(layer.project, current_user(request)),
        minimum,
    )
    return layer


def _project_out(project: Project, role: str | None) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "extent": services.geom_to_geojson(project.extent),
        "status": project.status,
        "settings": project.settings,
        "config_version": project.config_version,
        "my_role": role,
        "layer_count": project.layers.count(),
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _member_out(m: ProjectMember) -> dict[str, Any]:
    return {
        "user_id": m.user_id,
        "name": m.user.name,
        "email": m.user.email,
        "phone": m.user.phone,
        "role": m.role,
        "assigned_area": services.geom_to_geojson(m.assigned_area),
        "version": m.version,
    }


def _layer_out(layer: Layer) -> dict[str, Any]:
    return {
        "id": layer.id,
        "project_id": layer.project_id,
        "name": layer.name,
        "key": layer.key,
        "geometry_type": layer.geometry_type,
        "style": layer.style,
        "capture_profile": layer.capture_profile,
        "current_schema_version": layer.current_schema_version,
        "has_draft": bool(layer.draft_schema),
        "sort_order": layer.sort_order,
        "created_at": layer.created_at,
        "updated_at": layer.updated_at,
    }


# --- projects ----------------------------------------------------------------------------


@projects_router.get("", response=list[ProjectOut], operation_id="listProjects")
def list_projects(request: HttpRequest) -> list[dict[str, Any]]:
    membership = current_membership(request)
    user = current_user(request)
    return [
        _project_out(
            p,
            services.project_member_role(p, user)
            or ("manager" if membership.role in ("owner", "admin", "manager") else None),
        )
        for p in services.visible_projects(membership)
    ]


@projects_router.post("", response={201: ProjectOut}, operation_id="createProject")
def create_project(request: HttpRequest, payload: ProjectIn) -> Status[dict[str, Any]]:
    """Org managers and above create projects."""
    from precisecapture.common.permissions import require_role

    membership = require_role(request, "manager")
    project = services.create_project(membership.org, current_user(request), payload.dict())
    return Status(201, _project_out(project, "manager"))


@projects_router.get("/{project_id}", response=ProjectOut, operation_id="getProject")
def get_project(request: HttpRequest, project_id: uuid.UUID) -> dict[str, Any]:
    project, role = _project_for(request, project_id, "viewer")
    return _project_out(project, role)


@projects_router.patch("/{project_id}", response=ProjectOut, operation_id="updateProject")
def update_project(
    request: HttpRequest, project_id: uuid.UUID, payload: ProjectPatchIn
) -> dict[str, Any]:
    project, role = _project_for(request, project_id, "manager")
    return _project_out(services.update_project(project, payload.dict(exclude_unset=True)), role)


@projects_router.get(
    "/{project_id}/members", response=list[ProjectMemberOut], operation_id="listProjectMembers"
)
def list_members(request: HttpRequest, project_id: uuid.UUID) -> list[dict[str, Any]]:
    project, _ = _project_for(request, project_id, "manager")
    return [
        _member_out(m)
        for m in ProjectMember.objects.select_related("user")
        .filter(project=project)
        .order_by("user__name")
    ]


@projects_router.post(
    "/{project_id}/members", response={201: ProjectMemberOut}, operation_id="addProjectMember"
)
def add_member(
    request: HttpRequest, project_id: uuid.UUID, payload: ProjectMemberIn
) -> Status[dict[str, Any]]:
    project, _ = _project_for(request, project_id, "manager")
    return Status(201, _member_out(services.add_member(project, payload.dict())))


@projects_router.patch(
    "/{project_id}/members/{user_id}", response=ProjectMemberOut, operation_id="updateProjectMember"
)
def update_member(
    request: HttpRequest, project_id: uuid.UUID, user_id: uuid.UUID, payload: ProjectMemberPatchIn
) -> dict[str, Any]:
    project, _ = _project_for(request, project_id, "manager")
    return _member_out(services.update_member(project, user_id, payload.dict(exclude_unset=True)))


@projects_router.delete(
    "/{project_id}/members/{user_id}", response={204: None}, operation_id="removeProjectMember"
)
def remove_member(request: HttpRequest, project_id: uuid.UUID, user_id: uuid.UUID) -> Status[None]:
    project, _ = _project_for(request, project_id, "manager")
    services.remove_member(project, user_id)
    return Status(204, None)


# --- layers (nested under the project for list/create) -------------------------------------


@projects_router.get("/{project_id}/layers", response=list[LayerOut], operation_id="listLayers")
def list_layers(request: HttpRequest, project_id: uuid.UUID) -> list[dict[str, Any]]:
    project, _ = _project_for(request, project_id, "viewer")
    return [_layer_out(layer) for layer in Layer.objects.filter(project=project)]


@projects_router.post("/{project_id}/layers", response={201: LayerOut}, operation_id="createLayer")
def create_layer(
    request: HttpRequest, project_id: uuid.UUID, payload: LayerIn
) -> Status[dict[str, Any]]:
    project, _ = _project_for(request, project_id, "manager")
    return Status(201, _layer_out(services.create_layer(project, payload.dict())))


@projects_router.post(
    "/{project_id}/layers/from-template",
    response={201: LayerOut},
    operation_id="createLayerFromTemplate",
)
def create_layer_from_template(
    request: HttpRequest, project_id: uuid.UUID, payload: LayerFromTemplateIn
) -> Status[dict[str, Any]]:
    project, _ = _project_for(request, project_id, "manager")
    layer = schema_services.layer_from_template(
        project, payload.template_id, payload.name, payload.key
    )
    return Status(201, _layer_out(layer))


@projects_router.put(
    "/{project_id}/layers/order", response=list[LayerOut], operation_id="reorderLayers"
)
def reorder_layers(
    request: HttpRequest, project_id: uuid.UUID, payload: LayerReorderIn
) -> list[dict[str, Any]]:
    project, _ = _project_for(request, project_id, "manager")
    return [_layer_out(layer) for layer in services.reorder_layers(project, payload.layer_ids)]


@layers_router.get("/{layer_id}", response=LayerOut, operation_id="getLayer")
def get_layer(request: HttpRequest, layer_id: uuid.UUID) -> dict[str, Any]:
    return _layer_out(_layer_for(request, layer_id, "viewer"))


@layers_router.patch("/{layer_id}", response=LayerOut, operation_id="updateLayer")
def update_layer(
    request: HttpRequest, layer_id: uuid.UUID, payload: LayerPatchIn
) -> dict[str, Any]:
    layer = _layer_for(request, layer_id, "manager")
    return _layer_out(services.update_layer(layer, payload.dict(exclude_unset=True)))


@layers_router.delete("/{layer_id}", response={204: None}, operation_id="deleteLayer")
def delete_layer(request: HttpRequest, layer_id: uuid.UUID) -> Status[None]:
    """Allowed while the layer has no features."""
    services.delete_layer(_layer_for(request, layer_id, "manager"))
    return Status(204, None)


# --- schema draft / publish / versions -------------------------------------------------------


@layers_router.get("/{layer_id}/schema", response=SchemaOut, operation_id="getLayerSchema")
def get_schema(request: HttpRequest, layer_id: uuid.UUID) -> dict[str, Any]:
    layer = _layer_for(request, layer_id, "viewer")
    current = schema_services.current_schema(layer)
    cur = current.attributes if current else None
    return {
        "layer_id": layer.id,
        "current_version": layer.current_schema_version,
        "current": cur,
        "draft": layer.draft_schema,
        "draft_differs": layer.draft_schema is not None
        and (
            cur is None
            or schema_services._strip_version(cur)
            != schema_services._strip_version(layer.draft_schema)
        ),
    }


@layers_router.put("/{layer_id}/schema", response=SchemaOut, operation_id="saveLayerSchemaDraft")
def save_draft(request: HttpRequest, layer_id: uuid.UUID, payload: SchemaDraftIn) -> dict[str, Any]:
    """Save the draft attribute list. Publishing runs the full validation."""
    layer = _layer_for(request, layer_id, "manager")
    schema_services.save_draft(layer, payload.attributes)
    return get_schema(request, layer_id)


@layers_router.post(
    "/{layer_id}/schema/validate",
    response=SchemaPublishOut | dict[str, Any],
    operation_id="validateLayerSchema",
)
def validate_draft(
    request: HttpRequest, layer_id: uuid.UUID, payload: SchemaDraftIn
) -> dict[str, Any]:
    """Dry run of publish: returns {errors: []} without writing anything."""
    from precisecapture.projects.services import layer_keys

    layer = _layer_for(request, layer_id, "manager")
    previous = schema_services.current_schema(layer)
    doc = {
        **payload.attributes,
        "schemaVersion": 1,
        "layerId": layer.key,
        "version": layer.current_schema_version + 1,
    }
    errors = schema_services.validate_schema_document(
        doc,
        layer_keys=layer_keys(layer.project),
        previous=previous.attributes if previous else None,
    )
    return {"errors": errors}


@layers_router.post(
    "/{layer_id}/schema/publish", response=SchemaPublishOut, operation_id="publishLayerSchema"
)
def publish(request: HttpRequest, layer_id: uuid.UUID) -> dict[str, Any]:
    """Validate the draft, create an immutable version, bump config_version. 422 = errors."""
    layer = _layer_for(request, layer_id, "manager")
    version, warnings = schema_services.publish_schema(layer, current_user(request))
    layer.project.refresh_from_db(fields=["config_version"])
    return {
        "version": version.version,
        "config_version": layer.project.config_version,
        "warnings": warnings,
    }


@layers_router.get(
    "/{layer_id}/schema/versions",
    response=list[SchemaVersionOut],
    operation_id="listLayerSchemaVersions",
)
def list_versions(request: HttpRequest, layer_id: uuid.UUID) -> list[dict[str, Any]]:
    layer = _layer_for(request, layer_id, "viewer")
    return [
        {
            "version": v.version,
            "attributes": v.attributes,
            "published_at": v.published_at,
            "published_by": v.published_by_id,
        }
        for v in LayerSchemaVersion.objects.filter(layer=layer).order_by("version")
    ]


@layers_router.get(
    "/{layer_id}/schema/versions/{version}",
    response=SchemaVersionOut,
    operation_id="getLayerSchemaVersion",
)
def get_version(request: HttpRequest, layer_id: uuid.UUID, version: int) -> dict[str, Any]:
    layer = _layer_for(request, layer_id, "viewer")
    v = LayerSchemaVersion.objects.filter(layer=layer, version=version).first()
    if v is None:
        from precisecapture.common.errors import NotFound

        raise NotFound("Schema version not found")
    return {
        "version": v.version,
        "attributes": v.attributes,
        "published_at": v.published_at,
        "published_by": v.published_by_id,
    }


# --- capture profile -------------------------------------------------------------------------


def _profile_out(layer: Layer) -> dict[str, Any]:
    layer.project.refresh_from_db(fields=["config_version"])
    return {
        "layer_id": layer.id,
        "capture_profile": layer.capture_profile,
        "resolved": schema_services.resolved_profile(layer),
        "config_version": layer.project.config_version,
    }


@layers_router.get(
    "/{layer_id}/capture-profile", response=CaptureProfileOut, operation_id="getCaptureProfile"
)
def get_capture_profile(request: HttpRequest, layer_id: uuid.UUID) -> dict[str, Any]:
    return _profile_out(_layer_for(request, layer_id, "viewer"))


@layers_router.put(
    "/{layer_id}/capture-profile", response=CaptureProfileOut, operation_id="saveCaptureProfile"
)
def save_capture_profile(
    request: HttpRequest, layer_id: uuid.UUID, payload: CaptureProfileIn
) -> dict[str, Any]:
    """Validated against the JSON Schema and the cross-field rules; bumps config_version."""
    layer = _layer_for(request, layer_id, "manager")
    return _profile_out(schema_services.save_capture_profile(layer, payload.capture_profile))


# --- templates ----------------------------------------------------------------------------------


@layers_router.post(
    "/{layer_id}/save-as-template", response={201: TemplateOut}, operation_id="saveLayerAsTemplate"
)
def save_as_template(
    request: HttpRequest, layer_id: uuid.UUID, payload: TemplateIn
) -> Status[LayerTemplate]:
    layer = _layer_for(request, layer_id, "manager")
    return Status(
        201,
        schema_services.save_as_template(
            layer, current_user(request), payload.name, payload.description
        ),
    )


@templates_router.get("", response=list[TemplateOut], operation_id="listLayerTemplates")
def list_templates(request: HttpRequest) -> Any:
    return LayerTemplate.objects.all().order_by("name")


@templates_router.delete("/{template_id}", response={204: None}, operation_id="deleteLayerTemplate")
def delete_template(request: HttpRequest, template_id: uuid.UUID) -> Status[None]:
    from precisecapture.common.permissions import require_role

    require_role(request, "manager")
    deleted, _ = LayerTemplate.objects.filter(pk=template_id).delete()
    if not deleted:
        from precisecapture.common.errors import NotFound

        raise NotFound("Template not found")
    return Status(204, None)


# --- bundle --------------------------------------------------------------------------------------


@projects_router.get("/{project_id}/bundle", operation_id="getProjectBundle")
def bundle(request: HttpRequest, project_id: uuid.UUID) -> HttpResponse:
    """
    Everything a phone needs offline. ETag = hash(config_version, membership version, project
    role); If-None-Match gives 304. The server_seq watermark travels in X-Server-Seq (0 until M6).
    """
    import json

    from django.http import HttpResponse, HttpResponseNotModified

    project = services.get_project(project_id)
    membership = current_membership(request)
    user = current_user(request)
    pm = ProjectMember.objects.filter(project=project, user=user).first()
    role = require_project_role(membership, pm.role if pm else None, "viewer")
    etag = schema_services.bundle_etag(project, membership, pm.version if pm else None)
    if request.headers.get("If-None-Match") == etag:
        resp: HttpResponse = HttpResponseNotModified()
    else:
        body = schema_services.build_bundle(project, membership, role)
        resp = HttpResponse(json.dumps(body, default=str), content_type="application/json")
    resp["ETag"] = etag
    resp["Cache-Control"] = "private, no-cache"
    resp["X-Server-Seq"] = "0"
    return resp
