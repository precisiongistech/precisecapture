# @precisecapture/schema

The shared contract between the server, the web app and the mobile app. One source of truth,
implemented twice (TypeScript here, Python in `apps/api/precisecapture/common/`) and proven
identical by the shared test vectors.

| What | Where |
| --- | --- |
| Layer attribute schema (also the form) | `schemas/layer-schema.schema.json` |
| Capture profile (geometry capture rules) | `schemas/capture-profile.schema.json` |
| Sync wire formats (push/pull) | `schemas/sync.schema.json` |
| Expression language spec | `expressions.md` |
| Capture profile resolution and semantic rules | `capture-profile-resolution.md` |
| Pilot examples (Farmers, Farms, farm profile) | `examples/` |
| Shared test vectors | `test-vectors/` |

## Using it (TypeScript)

```ts
import {
  validateLayerSchema, validateCaptureProfile,            // Ajv, "strict" | "lenient"
  parse, evaluate, referencedFields, validateExpression,  // expression language
  resolveCaptureProfile, validateCaptureProfileSemantics, // capture profiles
  type LayerSchema, type CaptureProfile, type PushRequest,
} from "@precisecapture/schema";

const r = validateCaptureProfile(profileFromServer, "lenient"); // apps: ignore unknown keys
evaluate("${crop} = 'other'", { values: { crop: "other" }, now, today }); // true
```

## Developing

```bash
pnpm --filter @precisecapture/schema generate   # regenerate src/types.ts after editing a schema
pnpm --filter @precisecapture/schema test       # vitest: examples, vectors
pnpm --filter @precisecapture/schema build      # dist/ (ESM + CJS + d.ts)
make schema-test                                # TS + Python, from the repo root
```

Rules: changes must be backward compatible (new keys optional with defaults). A breaking change
bumps the major version, is listed in `CHANGELOG.md` under **BREAKING CHANGE**, and is announced
to the mobile team. Every behaviour change adds a test vector first.
