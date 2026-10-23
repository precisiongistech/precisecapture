# Capture profile resolution and semantic checks (v1)

Companion to `schemas/capture-profile.schema.json`. The JSON Schema says what a profile may
contain; this file says how the levels combine and which cross-field rules apply. Both are
implemented in TypeScript (`src/profile`) and Python (`precisecapture/common/capture_profile.py`)
and proven identical by `test-vectors/capture-profile-resolution.json` and
`test-vectors/capture-profile-semantics.json`.

## resolveCaptureProfile(org, project, layer, collectorOverrides)

Inputs are partial profiles (any may be null). Output is the effective profile the app obeys.

1. **Admin levels merge in order** org → project → layer. Objects deep-merge key by key; arrays
   and scalars are replaced by the lower level.
2. **Lockable objects** are the ones whose schema carries a `locked` flag: `modes`, `autoClose`,
   `snapping`, `trace`, `stream`, `gps`, `gps.averaging`, `offsetPoints`.
3. **A lock freezes the object as a whole.** When a level sets `locked: true` on a lockable object,
   that object (including nested objects and its own `locked` flag) is taken from that level and
   every lower level's version of it is ignored. Keys the locking level does not repeat are dropped
   (a lock is a statement of the complete object). A lock on `gps` therefore also freezes
   `gps.averaging`; a lock on `gps.averaging` alone leaves the rest of `gps` editable.
4. **`locked: false` at a lower level never unlocks** an object locked above it.
5. **Collector overrides** are applied last and only inside lockable objects that are not locked
   after step 3. Inside such an object the collector may change any key except `locked`. Keys
   outside lockable objects (`geometryType`, `schemaVersion`, `minVertices`, `validation`,
   `centroid`, `display`, and anything unknown) are ignored.
6. The output keeps the effective `locked` flags so the app can hide the toggles.

## validateCaptureProfileSemantics(profile, { geometryType?, layerKeys? })

Returns a list of `{ field, code, message }` (empty when valid). Rules that need context are
skipped when it is absent, so org- and project-level partial profiles can be checked too.

| Code | Field | Rule |
| --- | --- | --- |
| `not_allowed` | `modes.default` | must be one of `modes.allowed` (when both present) |
| `exclusive` | `stream.intervalSeconds` | `stream.intervalMeters` and `stream.intervalSeconds` cannot both be non-null |
| `not_allowed` | `stream.intervalMeters` | must be in `stream.allowedIntervalsMeters` (when both present) |
| `geometry` | `stream`, `snapping`, `trace`, `autoClose` | present only on line or polygon layers; the geometry comes from the context, else from `profile.geometryType`, else the rule is skipped |
| `unknown_layer` | `snapping.layers.N`, `trace.layers.N`, `validation.topology.noOverlapWith.N`, `validation.topology.noGapsWith.N` | every entry is `self` or one of `layerKeys` (when given) |
| `range` | `validation.maxAreaSqm` | `maxAreaSqm` must not be below `minAreaSqm` (when both present) |

The server runs both the JSON Schema and these checks on every save (M3). The web form builder
runs them live.
