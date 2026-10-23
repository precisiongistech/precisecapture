# @precisecapture/schema changelog

Semantic versioning. New keys are optional with safe defaults; a breaking change bumps the major
version and is announced to the mobile team under a **BREAKING CHANGE** heading.

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
