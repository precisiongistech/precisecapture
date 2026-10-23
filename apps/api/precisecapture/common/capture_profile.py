"""
Capture profile resolution and cross-field checks.

Spec: packages/schema/capture-profile-resolution.md. Mirrored in TypeScript
(packages/schema/src/profile). Both pass the shared vectors in
packages/schema/test-vectors/capture-profile-{resolution,semantics}.json.
"""

import copy
from collections.abc import Sequence
from typing import Any

from precisecapture.common.schema_validation import SchemaIssue

Profile = dict[str, Any]
Path = tuple[str, ...]

#: Objects whose schema carries a `locked` flag (dotted paths, as tuples).
LOCKABLE_PATHS: frozenset[Path] = frozenset(
    {
        ("modes",),
        ("autoClose",),
        ("snapping",),
        ("trace",),
        ("stream",),
        ("gps",),
        ("gps", "averaging"),
        ("offsetPoints",),
    }
)

#: The four objects that only make sense for line and polygon geometry.
_LINEAR_ONLY = ("stream", "snapping", "trace", "autoClose")

#: Where layer keys are referenced (parent path, key holding the array).
_LAYER_REF_PATHS: tuple[tuple[Path, str], ...] = (
    (("snapping",), "layers"),
    (("trace",), "layers"),
    (("validation", "topology"), "noOverlapWith"),
    (("validation", "topology"), "noGapsWith"),
)


def _is_frozen(path: Path, locked: set[Path]) -> bool:
    """True when `path` or any lockable ancestor of it has been locked."""
    return any(path[: len(lp)] == lp for lp in locked)


def _merge_admin(target: Profile, level: Profile, path: Path, locked: set[Path]) -> None:
    """Deep-merge one admin level into `target`, honouring locks set by higher levels."""
    for key, value in level.items():
        sub = (*path, key)
        if _is_frozen(sub, locked):
            continue
        if sub in LOCKABLE_PATHS and isinstance(value, dict) and value.get("locked") is True:
            target[key] = copy.deepcopy(value)  # a lock states the complete object
            locked.add(sub)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_admin(target[key], value, sub, locked)
        else:
            target[key] = copy.deepcopy(value)


def _merge_collector(target: Profile, overrides: Profile, path: Path, locked: set[Path]) -> None:
    """Apply collector overrides inside an unlocked lockable object (never `locked` itself)."""
    for key, value in overrides.items():
        if key == "locked":
            continue
        sub = (*path, key)
        if _is_frozen(sub, locked):
            continue
        if sub in LOCKABLE_PATHS:
            if isinstance(value, dict):
                target.setdefault(key, {})
                if isinstance(target[key], dict):
                    _merge_collector(target[key], value, sub, locked)
            continue
        target[key] = copy.deepcopy(value)


def _effective_locks(profile: Profile) -> set[Path]:
    """Lockable paths whose effective object carries `locked: true`."""
    locked: set[Path] = set()
    for lp in LOCKABLE_PATHS:
        node: Any = profile
        for part in lp:
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, dict) and node.get("locked") is True:
            locked.add(lp)
    return locked


def resolve_capture_profile(
    org: Profile | None,
    project: Profile | None,
    layer: Profile | None,
    collector_overrides: Profile | None,
) -> Profile:
    """Effective profile: org -> project -> layer -> collector, with locks (rules 1-6)."""
    result: Profile = {}
    locked: set[Path] = set()
    for level in (org, project, layer):
        # Locks set by a higher level (including ones copied in whole objects) freeze paths below.
        locked |= _effective_locks(result)
        _merge_admin(result, level or {}, (), locked)
    locked |= _effective_locks(result)
    for key, value in (collector_overrides or {}).items():
        sub: Path = (key,)
        if sub not in LOCKABLE_PATHS or not isinstance(value, dict) or _is_frozen(sub, locked):
            continue
        result.setdefault(key, {})
        if isinstance(result[key], dict):
            _merge_collector(result[key], value, sub, locked)
    return result


def _get(profile: Profile, path: Path) -> Any:
    node: Any = profile
    for part in path:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def validate_capture_profile_semantics(
    profile: Profile,
    *,
    geometry_type: str | None = None,
    layer_keys: Sequence[str] | None = None,
) -> list[SchemaIssue]:
    """The six cross-field rules a JSON Schema cannot express; context rules skip when absent."""
    issues: list[SchemaIssue] = []

    modes = profile.get("modes")
    if isinstance(modes, dict):
        allowed, default = modes.get("allowed"), modes.get("default")
        if isinstance(allowed, list) and default is not None and default not in allowed:
            issues.append(
                SchemaIssue("modes.default", "not_allowed", f"{default!r} is not in modes.allowed")
            )

    stream = profile.get("stream")
    if isinstance(stream, dict):
        meters, seconds = stream.get("intervalMeters"), stream.get("intervalSeconds")
        if meters is not None and seconds is not None:
            issues.append(
                SchemaIssue(
                    "stream.intervalSeconds",
                    "exclusive",
                    "Set either intervalMeters or intervalSeconds, not both",
                )
            )
        allowed_intervals = stream.get("allowedIntervalsMeters")
        if (
            meters is not None
            and isinstance(allowed_intervals, list)
            and meters not in allowed_intervals
        ):
            issues.append(
                SchemaIssue(
                    "stream.intervalMeters",
                    "not_allowed",
                    f"{meters} is not in allowedIntervalsMeters",
                )
            )

    geometry = geometry_type or profile.get("geometryType")
    if geometry in ("point", "none"):
        for key in _LINEAR_ONLY:
            if key in profile:
                issues.append(
                    SchemaIssue(key, "geometry", f"{key} applies only to line and polygon layers")
                )

    if layer_keys is not None:
        known = set(layer_keys)
        for parent, key in _LAYER_REF_PATHS:
            refs = _get(profile, (*parent, key))
            if not isinstance(refs, list):
                continue
            for i, ref in enumerate(refs):
                if ref != "self" and ref not in known:
                    field = ".".join((*parent, key, str(i)))
                    issues.append(
                        SchemaIssue(field, "unknown_layer", f"Layer {ref!r} is not in this project")
                    )

    validation = profile.get("validation")
    if isinstance(validation, dict):
        min_area, max_area = validation.get("minAreaSqm"), validation.get("maxAreaSqm")
        if min_area is not None and max_area is not None and max_area < min_area:
            issues.append(
                SchemaIssue(
                    "validation.maxAreaSqm", "range", "maxAreaSqm must not be below minAreaSqm"
                )
            )

    return issues
