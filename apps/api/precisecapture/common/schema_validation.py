"""
Validation of the shared contract documents with the same JSON Schemas the apps use.

The schemas live in packages/schema/schemas (located via settings.SCHEMA_DIR). The server
always validates strictly: unknown keys are errors, so typos are caught on save.
Errors come back as {field, code, message}, the shape used in problem JSON `errors[]`.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from django.conf import settings
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

SchemaName = Literal["layer-schema", "capture-profile", "sync"]
SyncDocument = Literal["PushRequest", "PushResponse", "PullResponse"]


@dataclass(frozen=True)
class SchemaIssue:
    field: str | None
    code: str
    message: str

    def as_dict(self) -> dict[str, str | None]:
        return {"field": self.field, "code": self.code, "message": self.message}


def schema_dir() -> Path:
    return Path(settings.SCHEMA_DIR)


@cache
def load_schema(name: SchemaName) -> dict[str, Any]:
    path = schema_dir() / "schemas" / f"{name}.schema.json"
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
    return data


@cache
def _validator(name: SchemaName, sync_document: SyncDocument | None = None) -> Draft202012Validator:
    schema = load_schema(name)
    if sync_document is not None:
        branch = next(b for b in schema["oneOf"] if b.get("title") == sync_document)
        schema = {
            "$schema": schema["$schema"],
            "$id": schema["$id"].removesuffix(".json") + f"/{sync_document.lower()}.json",
            "$defs": schema["$defs"],
            **branch,
        }
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _issue(err: ValidationError) -> SchemaIssue:
    parts = [str(p) for p in err.absolute_path]
    code = err.validator or "invalid"
    if code == "additionalProperties":
        # "Additional properties are not allowed ('x' was unexpected)"
        instance: Any = err.instance
        schema: Any = err.schema
        known = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
        extra = sorted(set(instance) - set(known.keys()))
        if extra:
            parts.append(extra[0])
    elif code == "required":
        missing = str(err.message).split("'")[1] if "'" in str(err.message) else ""
        if missing:
            parts.append(missing)
    return SchemaIssue(field=".".join(parts) or None, code=str(code), message=err.message)


def _collect(validator: Draft202012Validator, data: Any) -> list[SchemaIssue]:
    issues: list[SchemaIssue] = []
    seen: set[tuple[str | None, str, str]] = set()
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        # Surface the most specific sub-errors of combinators rather than "is not valid under any".
        leaves = list(err.context) if err.context else [err]
        for leaf in leaves:
            issue = _issue(leaf)
            key = (issue.field, issue.code, issue.message)
            if key not in seen:
                seen.add(key)
                issues.append(issue)
    return issues


def validate_layer_schema(data: Any) -> list[SchemaIssue]:
    return _collect(_validator("layer-schema"), data)


def validate_capture_profile(data: Any) -> list[SchemaIssue]:
    return _collect(_validator("capture-profile"), data)


def validate_sync_document(document: SyncDocument, data: Any) -> list[SchemaIssue]:
    return _collect(_validator("sync", document), data)


def load_example(name: str) -> Any:
    with (schema_dir() / "examples" / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def load_test_vectors(name: str) -> Any:
    with (schema_dir() / "test-vectors" / name).open(encoding="utf-8") as fh:
        return json.load(fh)
