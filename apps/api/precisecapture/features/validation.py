"""
Validate a feature's attributes against a published layer schema document.

Pure function: no database, no models. Used by features.services.write_feature() for both
sync and web writes. Semantics (ENGINEERING_NOTES.md §4, SPEC.md §9, expressions.md):

- `group` fields are layout only: their children are stored flat at the parent level.
- `repeat` fields store a list of row objects, validated recursively (paths `key.0.child`).
- A field whose `relevant` is false is dropped from the stored values, never an error.
- `calculate` fields are recomputed by the server unless the expression uses host-only
  functions (lookup, ghanapost_gps, today, now), in which case the device value is kept.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from precisecapture.common.expr import (
    Binary,
    Call,
    EvalContext,
    ExpressionParseError,
    Node,
    Unary,
    evaluate,
    parse,
    truthy,
)
from precisecapture.common.schema_validation import SchemaIssue

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$")
NUMERIC_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")

HOST_ONLY_FUNCTIONS = frozenset({"lookup", "ghanapost_gps", "today", "now"})
ATTACHMENT_TYPES = frozenset({"photo", "audio", "video", "file", "signature"})
STRING_TYPES = frozenset({"text", "barcode"})
NO_VALUE_TYPES = frozenset({"note", "group"})


@dataclass
class AttributeContext:
    now: datetime
    geom_area_m2: float | None = None
    geom_length_m: float | None = None
    previous: dict[str, Any] | None = None


@dataclass
class ValidationResult:
    values: dict[str, Any] = field(default_factory=dict)
    errors: list[SchemaIssue] = field(default_factory=list)
    unique_checks: list[tuple[str, Any]] = field(default_factory=list)
    relation_refs: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# --- helpers ------------------------------------------------------------------------------


def _flatten(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fields in document order with group children lifted to the parent level."""
    out: list[dict[str, Any]] = []
    for f in fields:
        if f.get("type") == "group":
            out.append(f)
            out.extend(_flatten(f.get("fields") or []))
        else:
            out.append(f)
    return out


def _i18n(value: Any, default: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value:
        return str(value.get("en") or next(iter(value.values())))
    return default


def _is_empty(v: Any) -> bool:
    return v is None or v == "" or (isinstance(v, list | dict) and len(v) == 0)


def _uses_host_functions(node: Node) -> bool:
    if isinstance(node, Call):
        if node.name in HOST_ONLY_FUNCTIONS:
            return True
        return any(_uses_host_functions(a) for a in node.args)
    if isinstance(node, Binary):
        return _uses_host_functions(node.left) or _uses_host_functions(node.right)
    if isinstance(node, Unary):
        return _uses_host_functions(node.operand)
    return False


def _options(
    fld: dict[str, Any], lists: dict[str, Any], values: dict[str, Any]
) -> list[Any] | None:
    raw = fld.get("options")
    if isinstance(raw, str) and raw.startswith("list:"):
        opts = lists.get(raw.removeprefix("list:"))
    else:
        opts = raw
    if not isinstance(opts, list):
        return None
    parent_key = fld.get("choiceFilterParent")
    parent_value = values.get(parent_key) if parent_key else None
    allowed: list[Any] = []
    for o in opts:
        if not isinstance(o, dict):
            continue
        flt = o.get("filter")
        filtered = parent_key and parent_value not in (None, "") and isinstance(flt, dict)
        if (
            filtered
            and isinstance(flt, dict)
            and parent_key in flt
            and flt[parent_key] != parent_value
        ):
            continue
        allowed.append(o.get("value"))
    return allowed


def _num(v: Any) -> float | int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return v
    if isinstance(v, str) and NUMERIC_RE.match(v.strip()):
        f = float(v.strip())
        return int(f) if f.is_integer() and "." not in v and "e" not in v.lower() else f
    return None


def _normalise_number(x: float | int) -> float | int:
    return int(x) if isinstance(x, float) and x.is_integer() else x


# --- the validator ---------------------------------------------------------------------------


class _Validator:
    def __init__(self, schema: dict[str, Any], context: AttributeContext) -> None:
        self.schema = schema
        self.lists: dict[str, Any] = schema.get("lists") or {}
        self.ctx = context
        self.result = ValidationResult()

    def run(self, attributes: dict[str, Any] | None) -> ValidationResult:
        self.result.values = self._validate_level(
            self.schema.get("fields") or [], dict(attributes or {}), prefix="", parent_scope=None
        )
        return self.result

    def _err(self, path: str, code: str, message: str) -> None:
        self.result.errors.append(SchemaIssue(field=path, code=code, message=message))

    def _eval_ctx(
        self, values: dict[str, Any], repeat_item: dict[str, Any] | None, self_value: Any
    ) -> EvalContext:
        return EvalContext(
            values=values,
            self_value=self_value,
            repeat_item=repeat_item,
            now=self.ctx.now.isoformat().replace("+00:00", "Z"),
            today=self.ctx.now.date().isoformat(),
            geom_area_m2=self.ctx.geom_area_m2,
            geom_length_m=self.ctx.geom_length_m,
        )

    def _evaluate(
        self,
        expr: str,
        values: dict[str, Any],
        repeat_item: dict[str, Any] | None,
        self_value: Any = None,
    ) -> Any:
        try:
            return evaluate(expr, self._eval_ctx(values, repeat_item, self_value))
        except ExpressionParseError:
            return None  # published schemas are parse-checked; treat a bad expression as null

    def _validate_level(
        self,
        fields: list[dict[str, Any]],
        incoming: dict[str, Any],
        *,
        prefix: str,
        parent_scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
        flat = _flatten(fields)
        known = {f["key"] for f in flat}
        for key in incoming:
            if key not in known:
                self._err(
                    f"{prefix}{key}", "unknown_field", f"'{key}' is not an attribute of this layer"
                )
        # Expressions see this level's raw values; inside a repeat row, the row wins over the parent
        # record (expressions.md). `scope` is the merged view used for option cascades.
        if parent_scope is None:
            values, repeat_item, scope = incoming, None, incoming
        else:
            values, repeat_item, scope = parent_scope, incoming, {**parent_scope, **incoming}
        out: dict[str, Any] = {}
        for fld in flat:
            key = fld["key"]
            path = f"{prefix}{key}"
            ftype = fld.get("type")
            present = key in incoming
            raw = incoming.get(key)
            if ftype in NO_VALUE_TYPES:
                if present:
                    self._err(path, "not_a_value", f"'{key}' is a {ftype} and carries no value")
                continue
            relevant = fld.get("relevant")
            if isinstance(relevant, str):
                rel = self._evaluate(relevant, values, repeat_item, raw)
                if rel is not None and not truthy(rel):
                    continue  # irrelevant: dropped, never an error
            if ftype == "calculate":
                out[key] = self._calculate(fld, raw, present, values, repeat_item)
                continue
            value = raw
            counted = ftype == "repeat" or ftype in ATTACHMENT_TYPES
            if _is_empty(value) and not (counted and value == [] and fld.get("min")):
                if self._is_required(fld, values, repeat_item):
                    self._err(path, "required", f"'{key}' is required")
                if present:
                    out[key] = "" if (ftype in STRING_TYPES and value == "") else None
                continue
            cleaned = self._coerce(fld, path, value, scope)
            if cleaned is _INVALID:
                continue
            constraint = fld.get("constraint")
            if isinstance(constraint, str):
                res = self._evaluate(constraint, values, repeat_item, cleaned)
                if res is not None and not truthy(res):
                    self._err(
                        path,
                        "constraint",
                        _i18n(fld.get("constraintMessage"), "Constraint not met"),
                    )
                    continue
            if fld.get("unique"):
                self.result.unique_checks.append((path, cleaned))
            if ftype == "relation":
                self.result.relation_refs.append(
                    (path, str((fld.get("relation") or {}).get("layer")), str(cleaned))
                )
            out[key] = cleaned
        return out

    def _is_required(
        self, fld: dict[str, Any], values: dict[str, Any], repeat_item: dict[str, Any] | None
    ) -> bool:
        req = fld.get("required")
        if isinstance(req, bool):
            return req
        if isinstance(req, str):
            res = self._evaluate(req, values, repeat_item)
            return res is not None and truthy(res)
        return False

    def _calculate(
        self,
        fld: dict[str, Any],
        raw: Any,
        present: bool,
        values: dict[str, Any],
        repeat_item: dict[str, Any] | None,
    ) -> Any:
        expr = fld.get("expression")
        if not isinstance(expr, str):
            return raw
        try:
            node = parse(expr)
        except ExpressionParseError:
            return raw
        if _uses_host_functions(node):
            if present:
                return raw
            prev = self.ctx.previous or {}
            return prev.get(fld["key"])
        value = evaluate(node, self._eval_ctx(values, repeat_item, None))
        if isinstance(value, float):
            return _normalise_number(value)
        return value

    # --- per type ---------------------------------------------------------------------------

    def _coerce(self, fld: dict[str, Any], path: str, value: Any, scope: dict[str, Any]) -> Any:
        ftype = fld.get("type")
        validation = fld.get("validation") or {}
        if ftype in STRING_TYPES or ftype in ("phone", "email"):
            if not isinstance(value, str):
                self._err(path, "type", f"'{fld['key']}' must be text")
                return _INVALID
            return self._check_string(fld, path, value, validation)
        if ftype in ("number", "decimal", "integer"):
            num = _num(value)
            if num is None:
                self._err(path, "type", f"'{fld['key']}' must be a number")
                return _INVALID
            if ftype == "integer" and float(num) != int(num):
                self._err(path, "type", f"'{fld['key']}' must be a whole number")
                return _INVALID
            num = int(num) if ftype == "integer" else _normalise_number(num)
            if "min" in validation and num < validation["min"]:
                self._err(path, "min", f"'{fld['key']}' must be at least {validation['min']}")
                return _INVALID
            if "max" in validation and num > validation["max"]:
                self._err(path, "max", f"'{fld['key']}' must be at most {validation['max']}")
                return _INVALID
            return num
        if ftype in ("date", "time", "datetime"):
            pattern = {"date": DATE_RE, "time": TIME_RE, "datetime": DATETIME_RE}[ftype]
            if not isinstance(value, str) or not pattern.match(value):
                self._err(path, "format", f"'{fld['key']}' must be a valid {ftype}")
                return _INVALID
            return value
        if ftype == "select_one":
            allowed = _options(fld, self.lists, scope)
            if allowed is not None and value not in allowed:
                self._err(path, "option", f"'{value}' is not an option for '{fld['key']}'")
                return _INVALID
            return value
        if ftype == "select_many":
            items = value if isinstance(value, list) else [value]
            allowed = _options(fld, self.lists, scope)
            if len(set(map(str, items))) != len(items):
                self._err(path, "type", f"'{fld['key']}' has duplicate selections")
                return _INVALID
            bad = [v for v in items if allowed is not None and v not in allowed]
            if bad:
                self._err(path, "option", f"{bad[0]!r} is not an option for '{fld['key']}'")
                return _INVALID
            return items
        if ftype == "yes_no":
            if isinstance(value, bool):
                return "yes" if value else "no"
            if value in ("yes", "no"):
                return value
            self._err(path, "type", f"'{fld['key']}' must be yes or no")
            return _INVALID
        if ftype in ATTACHMENT_TYPES:
            return self._check_attachments(fld, path, value)
        if ftype == "geopoint":
            return self._check_geopoint(fld, path, value)
        if ftype == "relation":
            if not isinstance(value, str) or not _is_uuid(value):
                self._err(path, "type", f"'{fld['key']}' must reference a feature id")
                return _INVALID
            return value
        if ftype == "repeat":
            return self._check_repeat(fld, path, value, scope)
        return value

    def _check_string(
        self, fld: dict[str, Any], path: str, value: str, validation: dict[str, Any]
    ) -> Any:
        ftype = fld.get("type")
        if ftype == "phone" and not E164_RE.match(value):
            self._err(path, "format", f"'{fld['key']}' must be an E.164 phone number")
            return _INVALID
        if ftype == "email" and not EMAIL_RE.match(value):
            self._err(path, "format", f"'{fld['key']}' must be an email address")
            return _INVALID
        if "minLength" in validation and len(value) < validation["minLength"]:
            self._err(
                path,
                "min_length",
                f"'{fld['key']}' needs at least {validation['minLength']} characters",
            )
            return _INVALID
        if "maxLength" in validation and len(value) > validation["maxLength"]:
            self._err(
                path,
                "max_length",
                f"'{fld['key']}' allows at most {validation['maxLength']} characters",
            )
            return _INVALID
        pattern = validation.get("pattern")
        if isinstance(pattern, str):
            try:
                ok = re.search(pattern, value) is not None
            except re.error:
                ok = True
            if not ok:
                self._err(path, "pattern", f"'{fld['key']}' does not match the required pattern")
                return _INVALID
        return value

    def _check_attachments(self, fld: dict[str, Any], path: str, value: Any) -> Any:
        items = value if isinstance(value, list) else [value]
        if not all(isinstance(v, str) and _is_uuid(v) for v in items):
            self._err(path, "type", f"'{fld['key']}' must be a list of attachment ids")
            return _INVALID
        lo, hi = fld.get("min"), fld.get("max")
        if lo is not None and len(items) < lo:
            self._err(path, "min_count", f"'{fld['key']}' needs at least {lo} file(s)")
            return _INVALID
        if hi is not None and len(items) > hi:
            self._err(path, "max_count", f"'{fld['key']}' allows at most {hi} file(s)")
            return _INVALID
        return items

    def _check_geopoint(self, fld: dict[str, Any], path: str, value: Any) -> Any:
        lon = lat = None
        if isinstance(value, dict):
            if value.get("type") == "Point" and isinstance(value.get("coordinates"), list):
                coords = value["coordinates"]
                if len(coords) >= 2:
                    lon, lat = _num(coords[0]), _num(coords[1])
            elif "lon" in value and "lat" in value:
                lon, lat = _num(value["lon"]), _num(value["lat"])
        if lon is None or lat is None or not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            self._err(path, "type", f"'{fld['key']}' must be a point with lon/lat")
            return _INVALID
        return {"type": "Point", "coordinates": [lon, lat]}

    def _check_repeat(
        self, fld: dict[str, Any], path: str, value: Any, parent: dict[str, Any]
    ) -> Any:
        if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
            self._err(path, "type", f"'{fld['key']}' must be a list of rows")
            return _INVALID
        lo, hi = fld.get("min"), fld.get("max")
        if lo is not None and len(value) < lo:
            self._err(path, "min_count", f"'{fld['key']}' needs at least {lo} row(s)")
        if hi is not None and len(value) > hi:
            self._err(path, "max_count", f"'{fld['key']}' allows at most {hi} row(s)")
        rows: list[dict[str, Any]] = []
        for i, row in enumerate(value):
            rows.append(
                self._validate_level(
                    fld.get("fields") or [], dict(row), prefix=f"{path}.{i}.", parent_scope=parent
                )
            )
        return rows


class _Invalid:
    pass


_INVALID = _Invalid()


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def validate_attributes(
    schema: dict[str, Any], attributes: dict[str, Any] | None, *, context: AttributeContext
) -> ValidationResult:
    """Validate and clean `attributes` against a published layer schema document."""
    return _Validator(schema, context).run(attributes)
