# @precisecapture/api-client

Typed TypeScript client for the PreciseCapture API, generated from `contract/openapi.json`.

```ts
import { PreciseCaptureClient, ApiError } from "@precisecapture/api-client";

const api = new PreciseCaptureClient({ baseUrl: "https://capture.example.org", tokens: myTokenStore });
await api.login("+233241234567", "secret", deviceId);          // or verifyOtp(destination, code)
const projects = await api.get("/api/v1/me/projects");
api.orgId = projects[0].org_id;
const bundle = await api.get("/api/v1/projects/{project_id}/bundle", { path: { project_id: projects[0].id } });
try {
  await api.post("/api/v1/sync/push", { body: pushRequest });
} catch (e) {
  if (e instanceof ApiError) console.log(e.status, e.code, e.fieldErrors);
}
```

- Bearer token and `X-Org-Id` are added automatically (`orgId` on the client or per call).
- `Idempotency-Key` is added to non-sync writes (sync uses `change_id`).
- A 401 triggers one refresh (shared across parallel calls) and a retry; a failed refresh calls
  `onSignedOut`.
- Runtime agnostic: pass your own `fetch` and `TokenStore` (React Native keystore, browser storage).

`make contract` regenerates `src/schema.ts`; `pnpm --filter @precisecapture/api-client lint` fails when it is stale.
