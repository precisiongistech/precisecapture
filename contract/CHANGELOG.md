# API contract changelog

`contract/openapi.json` is the contract with the mobile app. Each entry lists what the phone can
rely on; breaking changes appear under **BREAKING CHANGE** and are announced to Selorm.

## v0.1.1 (2026-10-24)

Milestone M6. No shape changes: `syncPush` and `syncPull` are now implemented (no longer 501).

- `syncPush`: idempotent on `change_id` (replays return `duplicate`), per-change results per
  ENGINEERING_NOTES.md §2, `Content-Encoding: gzip` accepted, 200 changes max (422 above).
- `syncPull`: latest state per feature since `cursor`, review `status` and `review_note` included,
  `qa_flags` may contain `conflict`.
- New: `listConflicts`, `getConflict`, `resolveConflict` (web, managers).
- Web feature endpoints from M5 (`listFeatures`, `createFeature`, `getFeature`, `getFeatureHistory`,
  `updateFeature`, `deleteFeature`, `restoreFeature`, `reviewFeature`, `getLayerTile`).

## v0.1.0 (2026-10-23)

First published contract (milestone M4). Git tag `contract-v0.1.0`.

- Auth: `login`, `refresh`, `logout`, `otpRequest`, `otpVerify`; `me`, `myProjects`;
  `registerDevice`, `listDevices`, `revokeDevice`; `wellKnown`, `health`.
- Organisations: create/get/update, members, invitations (admin web app).
- Projects and layers: CRUD, members, layer order, schema draft/validate/publish/versions,
  capture profile with the resolved view, templates, `getProjectBundle` (ETag, 304, `X-Server-Seq`).
- Sync (`syncPush`, `syncPull`) and attachments (`createAttachment`, `completeAttachment`,
  `getAttachment`): **typed stubs returning 501** until M6/M7. Their request and response shapes
  are final and match `packages/schema/schemas/sync.schema.json`.
- Every operation documents RFC 9457 problem responses; tenant operations document `X-Org-Id`.
- Examples on every schema and on the sync/attachment operations; `contract/examples/*.json`.
- `make mock` serves the contract with Prism on :4010 (static examples);
  `@precisecapture/api-client` wraps it for TypeScript.
