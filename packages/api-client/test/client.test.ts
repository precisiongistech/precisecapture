import { describe, expect, it, vi } from "vitest";

import { ApiError, MemoryTokenStore, PreciseCaptureClient } from "../src/index.js";

type Call = { url: string; init: RequestInit };

function fakeFetch(handler: (call: Call, n: number) => Response | Promise<Response>) {
  const calls: Call[] = [];
  const fn = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const call = { url: String(url), init: init ?? {} };
    calls.push(call);
    return handler(call, calls.length);
  });
  return { fn: fn as unknown as typeof fetch, calls };
}

const json = (status: number, body: unknown, type = "application/json") =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": type } });

const pair = { access_token: "A1", refresh_token: "R1", token_type: "Bearer", expires_in: 900 };

describe("PreciseCaptureClient", () => {
  it("sends bearer, X-Org-Id and Idempotency-Key, and parses JSON", async () => {
    const f = fakeFetch(() => json(201, { id: "p1", name: "Western North" }));
    const client = new PreciseCaptureClient({ baseUrl: "https://api.test/", fetch: f.fn, orgId: "org-1", idempotencyKey: () => "key-1" });
    await client.tokens.setTokens(pair);
    const out = await client.post("/api/v1/projects", { body: { name: "Western North", description: "", status: "active" } });
    expect(out.name).toBe("Western North");
    const h = f.calls[0]!.init.headers as Record<string, string>;
    expect(f.calls[0]!.url).toBe("https://api.test/api/v1/projects");
    expect(h.Authorization).toBe("Bearer A1");
    expect(h["X-Org-Id"]).toBe("org-1");
    expect(h["Idempotency-Key"]).toBe("key-1");
  });

  it("fills path and query parameters and omits X-Org-Id for user-only routes", async () => {
    const f = fakeFetch(() => json(200, { items: [], next_cursor: 0, has_more: false, config_version: 1 }));
    const client = new PreciseCaptureClient({ baseUrl: "https://api.test", fetch: f.fn, orgId: "org-1" });
    await client.get("/api/v1/sync/pull", { query: { project: "p1", cursor: 7, limit: 100 } });
    expect(f.calls[0]!.url).toBe("https://api.test/api/v1/sync/pull?project=p1&cursor=7&limit=100");
    expect((f.calls[0]!.init.headers as Record<string, string>)["Idempotency-Key"]).toBeUndefined(); // GET
    await client.get("/api/v1/me");
    expect((f.calls[1]!.init.headers as Record<string, string>)["X-Org-Id"]).toBeUndefined();
    await client.get("/api/v1/layers/{layer_id}/schema/versions/{version}", { path: { layer_id: "L1", version: 2 } });
    expect(f.calls[2]!.url).toBe("https://api.test/api/v1/layers/L1/schema/versions/2");
  });

  it("no Idempotency-Key on sync push (change_id is the idempotency key there)", async () => {
    const f = fakeFetch(() => json(200, { results: [], last_seq: 0 }));
    const client = new PreciseCaptureClient({ baseUrl: "https://api.test", fetch: f.fn, orgId: "org-1" });
    await client.post("/api/v1/sync/push", { body: { project_id: "p", changes: [] } });
    expect((f.calls[0]!.init.headers as Record<string, string>)["Idempotency-Key"]).toBeUndefined();
  });

  it("turns problem JSON into ApiError with field errors", async () => {
    const problem = {
      type: "https://precisecapture.app/problems/validation-failed",
      title: "Validation failed",
      status: 422,
      errors: [{ field: "fields.0.key", code: "duplicate", message: "Key used twice" }],
    };
    const f = fakeFetch(() => json(422, problem, "application/problem+json"));
    const client = new PreciseCaptureClient({ baseUrl: "https://api.test", fetch: f.fn, orgId: "o" });
    const err = await client.post("/api/v1/layers/{layer_id}/schema/publish", { path: { layer_id: "L" } }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const e = err as ApiError;
    expect(e.status).toBe(422);
    expect(e.code).toBe("validation-failed");
    expect(e.fieldErrors).toEqual({ "fields.0.key": "Key used twice" });
  });

  it("refreshes once on 401 and retries; parallel calls share the refresh", async () => {
    let refreshes = 0;
    const f = fakeFetch((call) => {
      const h = call.init.headers as Record<string, string>;
      if (call.url.endsWith("/auth/refresh")) {
        refreshes++;
        return json(200, { ...pair, access_token: "A2", refresh_token: "R2" });
      }
      if (h.Authorization === "Bearer A1") return json(401, { type: "about:blank", title: "Unauthorized", status: 401 }, "application/problem+json");
      return json(200, { user: { id: "u" }, memberships: [], device_id: null });
    });
    const store = new MemoryTokenStore();
    store.setTokens(pair);
    const client = new PreciseCaptureClient({ baseUrl: "https://api.test", fetch: f.fn, tokens: store });
    const [a, b] = await Promise.all([client.get("/api/v1/me"), client.get("/api/v1/me")]);
    expect(a.user.id).toBe("u");
    expect(b.user.id).toBe("u");
    expect(refreshes).toBe(1);
    expect(store.getAccessToken()).toBe("A2");
  });

  it("signs out when the refresh fails", async () => {
    const f = fakeFetch((call) => (call.url.endsWith("/auth/refresh") ? json(401, { title: "x", status: 401, type: "about:blank" }) : json(401, { title: "x", status: 401, type: "about:blank" })));
    const signedOut = vi.fn();
    const store = new MemoryTokenStore();
    store.setTokens(pair);
    const client = new PreciseCaptureClient({ baseUrl: "https://api.test", fetch: f.fn, tokens: store, onSignedOut: signedOut });
    await expect(client.get("/api/v1/me")).rejects.toBeInstanceOf(ApiError);
    expect(signedOut).toHaveBeenCalledOnce();
    expect(store.getAccessToken()).toBeNull();
  });

  it("login stores the pair; 204 resolves to undefined", async () => {
    const f = fakeFetch((call) => (call.url.endsWith("/auth/login") ? json(200, pair) : new Response(null, { status: 204 })));
    const client = new PreciseCaptureClient({ baseUrl: "https://api.test", fetch: f.fn });
    await client.login("ama@example.org", "pw", "dev-1");
    expect(JSON.parse(String(f.calls[0]!.init.body))).toEqual({ identifier: "ama@example.org", password: "pw", device_id: "dev-1" });
    expect(await client.tokens.getAccessToken()).toBe("A1");
    await expect(client.delete("/api/v1/devices/{device_id}", { path: { device_id: "dev-1" } })).resolves.toBeUndefined();
  });
});
