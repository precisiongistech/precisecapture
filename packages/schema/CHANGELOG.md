# @precisecapture/schema changelog

Semantic versioning. New keys are optional with safe defaults; a breaking change bumps the major
version and is announced to the mobile team under a **BREAKING CHANGE** heading.

## 0.2.0 (2026-10-24)

Added `sourceName`, `hiddenOnDevice` and `validation.spatialRules` (optional).

- `layer-schema` fields: `sourceName` (original column name of an imported dataset) and
  `hiddenOnDevice` (kept on the server and in exports, never sent to phones; default `false`).
- `capture-profile`: `validation.spatialRules[]` (checks against reference layers: `referenceLayer`,
  `predicate`, `bufferMeters`, `minOverlapSqm`, `action`, `message`).
- `validateCaptureProfileSemantics` takes an optional `referenceLayerKeys` context; a spatial rule's
  `referenceLayer` must exist (`unknown_layer`) and be a reference layer (`not_reference`).
- No existing key changed; every 0.1.0 document still validates.

## 0.1.0 (2026-10-23)

First published contract (milestone M1).

- JSON Schemas (draft 2020-12): `layer-schema`, `capture-profile`, `sync` (push request, push
  response, pull response). Layer references are layer **keys** (`^[a-z][a-z0-9_]{0,62}$`) or
  `self`.
- Generated TypeScript types (`LayerSchema`, `CaptureProfile`, `PushRequest`, `PushResponse`,
  `PullResponse`, `Change`, `ChangeResult`, `PullItem`, ...).
- Ajv validators with `strict` (server) and `lenient` (apps: unknown keys stripped) modes.
- Expression language v1 (`expressions.md`): `parse`, `evaluate`, `referencedFields`,
  `validateExpression`; 107 shared test vectors.
- Capture profile resolution and semantic checks (`capture-profile-resolution.md`):
  `resolveCaptureProfile`, `validateCaptureProfileSemantics`; 35 shared test vectors.
- Pilot examples: Farmers and Farms layer schemas, farm capture profile.
