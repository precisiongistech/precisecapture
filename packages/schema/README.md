# @precisecapture/schema

The shared contract between the server, the web app and the mobile app.

- `schemas/capture-profile.schema.json` — per-layer geometry capture rules
- `schemas/layer-schema.schema.json` — a layer's attributes (also its form)
- `examples/` — the pilot: Farmers (no geometry) and Farms (polygon) layers, and the farm capture profile
- `expressions.md` — the expression language (relevant / required / constraint / calculate)
- `test-vectors/expressions.json` — cases both the TypeScript and Python evaluators must pass

Rules: changes must be backward compatible (new keys optional with defaults). Breaking changes bump the major version and must be announced to the mobile team.
