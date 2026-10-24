"""
OpenAPI post-processing: the document Ninja builds, plus

- a reusable `Problem` schema and the error responses every operation can return,
- examples pulled from the Pydantic `examples=` field metadata into component-level examples,
- the `X-Org-Id` header parameter on every tenant operation, documented once,
- stable ordering so `contract/openapi.json` diffs are meaningful.
"""

from typing import Any

from ninja import NinjaAPI
from ninja.openapi.schema import OpenAPISchema

ERROR_RESPONSES: dict[str, str] = {
    "400": "Bad request (e.g. missing or malformed X-Org-Id)",
    "401": "Missing, invalid or expired access token",
    "403": "Not a member, or role too low",
    "404": "Not found (or not visible in this organisation)",
    "409": "Conflict with the current state",
    "422": "Validation failed; `errors[]` lists each field",
    "429": "Rate limited",
}

PROBLEM_SCHEMA: dict[str, Any] = {
    "title": "Problem",
    "description": "RFC 9457 problem details; content type application/problem+json",
    "type": "object",
    "required": ["type", "title", "status"],
    "properties": {
        "type": {
            "type": "string",
            "example": "https://precisecapture.app/problems/validation-failed",
        },
        "title": {"type": "string", "example": "Validation failed"},
        "status": {"type": "integer", "example": 422},
        "detail": {"type": "string", "example": "One or more fields are invalid."},
        "instance": {"type": "string", "example": "/api/v1/layers/0192.../schema/publish"},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "field": {"type": "string", "nullable": True, "example": "fields.0.key"},
                    "code": {"type": "string", "example": "duplicate"},
                    "message": {"type": "string", "example": "Key 'crop' is used twice"},
                },
            },
        },
    },
}

ORG_HEADER_PARAM: dict[str, Any] = {
    "name": "X-Org-Id",
    "in": "header",
    "required": True,
    "description": "The organisation to act in; the user must be a member.",
    "schema": {"type": "string", "format": "uuid"},
}


def _operation_examples() -> dict[str, dict[str, Any]]:
    """operationId -> {"request": example, "response": (status, example)}; imported lazily."""
    from precisecapture.attachments.schemas import ATTACHMENT_UPLOAD_EXAMPLE
    from precisecapture.sync.schemas import (
        PULL_RESPONSE_EXAMPLE,
        PUSH_REQUEST_EXAMPLE,
        PUSH_RESPONSE_EXAMPLE,
    )

    return {
        "syncPush": {"request": PUSH_REQUEST_EXAMPLE, "response": ("200", PUSH_RESPONSE_EXAMPLE)},
        "syncPull": {"response": ("200", PULL_RESPONSE_EXAMPLE)},
        "createAttachment": {"response": ("201", ATTACHMENT_UPLOAD_EXAMPLE)},
    }


class PreciseCaptureAPI(NinjaAPI):
    def get_openapi_schema(self, **kwargs: Any) -> OpenAPISchema:
        schema = super().get_openapi_schema(**kwargs)
        _normalise_response_keys(schema)
        _add_problem_responses(schema)
        _lift_field_examples(schema)
        _add_operation_examples(schema)
        return schema


def _add_operation_examples(schema: dict[str, Any]) -> None:
    examples = _operation_examples()
    for ops in schema.get("paths", {}).values():
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            ex = examples.get(op.get("operationId", ""))
            if not ex:
                continue
            if "request" in ex:
                content = (
                    op.setdefault("requestBody", {})
                    .setdefault("content", {})
                    .setdefault("application/json", {})
                )
                content["example"] = ex["request"]
            if "response" in ex:
                status, body = ex["response"]
                content = (
                    op.setdefault("responses", {})
                    .setdefault(status, {})
                    .setdefault("content", {})
                    .setdefault("application/json", {})
                )
                content["example"] = body


def _normalise_response_keys(schema: dict[str, Any]) -> None:
    """Ninja keys responses by int, JSON by string: use strings everywhere (no duplicate keys)."""
    for ops in schema.get("paths", {}).values():
        for method, op in ops.items():
            if method in ("get", "post", "put", "patch", "delete") and "responses" in op:
                op["responses"] = {str(k): v for k, v in op["responses"].items()}


def _add_problem_responses(schema: dict[str, Any]) -> None:
    components = schema.setdefault("components", {})
    components.setdefault("schemas", {})["Problem"] = PROBLEM_SCHEMA
    problem_content = {
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
    }
    for _path, ops in schema.get("paths", {}).items():
        for method, op in ops.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            responses = op.setdefault("responses", {})
            secured = bool(op.get("security"))
            tenant = secured and _is_tenant_operation(op)
            for code, text in ERROR_RESPONSES.items():
                if code in ("401", "403") and not secured:
                    continue
                if code == "400" and not tenant:
                    continue
                responses.setdefault(code, {"description": text, "content": problem_content})
            if tenant:
                params = op.setdefault("parameters", [])
                if not any(p.get("name") == "X-Org-Id" for p in params):
                    params.insert(0, ORG_HEADER_PARAM)


def _is_tenant_operation(op: dict[str, Any]) -> bool:
    return any("TenantAuth" in sec for sec in op.get("security") or [])


def _lift_field_examples(schema: dict[str, Any]) -> None:
    """Give every component schema an object-level example assembled from its field examples."""
    for name, comp in schema.get("components", {}).get("schemas", {}).items():
        if name == "Problem" or comp.get("type") != "object" or "example" in comp:
            continue
        example: dict[str, Any] = {}
        for field, spec in (comp.get("properties") or {}).items():
            value = _example_for(spec, schema)
            if value is not None or field in (comp.get("required") or []):
                example[field] = value
        if example:
            comp["example"] = example


def _example_for(spec: dict[str, Any], schema: dict[str, Any], depth: int = 0) -> Any:
    if depth > 4:
        return None
    if spec.get("examples"):
        return spec["examples"][0]
    if "example" in spec:
        return spec["example"]
    if "default" in spec:
        return spec["default"]
    if "$ref" in spec:
        target = schema["components"]["schemas"].get(spec["$ref"].rsplit("/", 1)[-1], {})
        if "example" in target:
            return target["example"]
        return _example_for(target, schema, depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        if key in spec:
            for sub in spec[key]:
                if sub.get("type") != "null":
                    value = _example_for(sub, schema, depth + 1)
                    if value is not None:
                        return value
            return None
    t = spec.get("type")
    if t == "object":
        props = spec.get("properties") or {}
        if not props:
            return {}
        return {k: _example_for(v, schema, depth + 1) for k, v in props.items()}
    if t == "array":
        item = _example_for(spec.get("items") or {}, schema, depth + 1)
        return [item] if item is not None else []
    if "enum" in spec:
        return spec["enum"][0]
    if t == "string":
        fmt = spec.get("format")
        return {
            "uuid": "0192f0c1-1234-7abc-8def-000000000001",
            "date-time": "2026-10-22T10:15:02Z",
            "email": "ama@example.org",
        }.get(fmt or "", "string")
    if t == "integer":
        return 1
    if t == "number":
        return 1.5
    if t == "boolean":
        return True
    return None
