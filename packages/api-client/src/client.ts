/**
 * A thin fetch client over the generated types.
 *
 * - Bearer token + X-Org-Id on every call (org optional for /me, /auth, /devices, POST /orgs).
 * - Idempotency-Key on non-sync writes (the server honours it from M5).
 * - Problem JSON (RFC 9457) parsed into a typed ApiError.
 * - 401 -> one refresh (single-flight across parallel calls) -> retry once.
 * - Runtime-agnostic: pass your own fetch and token store (browser, React Native).
 */
import type { components, paths } from "./schema.js";

export type Paths = paths;
export type Schemas = components["schemas"];
export type Problem = Schemas["Problem"];
export type TokenPair = Schemas["TokenPairOut"];

export interface TokenStore {
  getAccessToken(): Promise<string | null> | string | null;
  getRefreshToken(): Promise<string | null> | string | null;
  setTokens(pair: TokenPair | null): Promise<void> | void;
}

export class MemoryTokenStore implements TokenStore {
  private pair: TokenPair | null = null;
  getAccessToken(): string | null {
    return this.pair?.access_token ?? null;
  }
  getRefreshToken(): string | null {
    return this.pair?.refresh_token ?? null;
  }
  setTokens(pair: TokenPair | null): void {
    this.pair = pair;
  }
}

export class ApiError extends Error {
  override readonly name = "ApiError";
  constructor(
    public readonly status: number,
    public readonly problem: Problem,
  ) {
    super(problem.detail ?? problem.title);
  }
  get code(): string {
    return this.problem.type.split("/").pop() ?? "error";
  }
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const e of this.problem.errors ?? []) if (e.field) out[e.field] = e.message;
    return out;
  }
}

export interface ClientOptions {
  baseUrl: string;
  tokens?: TokenStore;
  fetch?: typeof fetch;
  orgId?: string | null;
  /** Called when a refresh fails: the user must log in again. */
  onSignedOut?: () => void;
  idempotencyKey?: () => string;
}

type Method = "get" | "post" | "put" | "patch" | "delete";
type PathsWith<M extends Method> = { [P in keyof Paths]: Paths[P] extends Record<M, unknown> ? P : never }[keyof Paths];
type Op<P extends keyof Paths, M extends Method> = Paths[P] extends Record<M, infer O> ? O : never;
type Params<O> = O extends { parameters: infer P } ? P : never;
type PathParams<O> = Params<O> extends { path: infer P } ? P : Record<string, never>;
type QueryParams<O> = Params<O> extends { query?: infer Q } ? Q : undefined;
type Body<O> = O extends { requestBody: { content: { "application/json": infer B } } } ? B : O extends { requestBody?: { content: { "application/json": infer B } } } ? B | undefined : undefined;
type Ok<O> = O extends { responses: infer R } ? R extends Record<200, { content: { "application/json": infer T } }> ? T : R extends Record<201, { content: { "application/json": infer T } }> ? T : void : never;

export interface RequestOptions<O> {
  path?: PathParams<O>;
  query?: QueryParams<O>;
  body?: Body<O>;
  headers?: Record<string, string>;
  /** Override the client's org for this call; null sends no X-Org-Id. */
  orgId?: string | null;
  signal?: AbortSignal;
}

const NO_ORG_PREFIXES = ["/api/v1/auth/", "/api/v1/me", "/api/v1/devices", "/api/v1/health", "/api/v1/.well-known", "/api/v1/invitations"];

export class PreciseCaptureClient {
  readonly baseUrl: string;
  readonly tokens: TokenStore;
  orgId: string | null;
  private readonly fetchImpl: typeof fetch;
  private readonly onSignedOut: (() => void) | undefined;
  private readonly newKey: () => string;
  private refreshing: Promise<boolean> | null = null;

  constructor(options: ClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.tokens = options.tokens ?? new MemoryTokenStore();
    this.orgId = options.orgId ?? null;
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.onSignedOut = options.onSignedOut;
    this.newKey = options.idempotencyKey ?? (() => globalThis.crypto.randomUUID());
  }

  get<P extends PathsWith<"get">>(path: P, opts: RequestOptions<Op<P, "get">> = {}): Promise<Ok<Op<P, "get">>> {
    return this.request("get", path, opts);
  }
  post<P extends PathsWith<"post">>(path: P, opts: RequestOptions<Op<P, "post">> = {}): Promise<Ok<Op<P, "post">>> {
    return this.request("post", path, opts);
  }
  put<P extends PathsWith<"put">>(path: P, opts: RequestOptions<Op<P, "put">> = {}): Promise<Ok<Op<P, "put">>> {
    return this.request("put", path, opts);
  }
  patch<P extends PathsWith<"patch">>(path: P, opts: RequestOptions<Op<P, "patch">> = {}): Promise<Ok<Op<P, "patch">>> {
    return this.request("patch", path, opts);
  }
  delete<P extends PathsWith<"delete">>(path: P, opts: RequestOptions<Op<P, "delete">> = {}): Promise<Ok<Op<P, "delete">>> {
    return this.request("delete", path, opts);
  }

  // --- auth helpers -------------------------------------------------------------------

  async login(identifier: string, password: string, deviceId?: string): Promise<TokenPair> {
    const pair = await this.post("/api/v1/auth/login", { body: { identifier, password, device_id: deviceId ?? null } });
    await this.tokens.setTokens(pair);
    return pair;
  }

  async verifyOtp(destination: string, code: string, deviceId?: string): Promise<TokenPair> {
    const pair = await this.post("/api/v1/auth/otp/verify", { body: { destination, code, device_id: deviceId ?? null } });
    await this.tokens.setTokens(pair);
    return pair;
  }

  async logout(): Promise<void> {
    const refresh = await this.tokens.getRefreshToken();
    if (refresh) await this.post("/api/v1/auth/logout", { body: { refresh_token: refresh } }).catch(() => undefined);
    await this.tokens.setTokens(null);
  }

  /** Single-flight refresh: parallel 401s share one refresh call. */
  refresh(): Promise<boolean> {
    this.refreshing ??= (async () => {
      try {
        const refresh = await this.tokens.getRefreshToken();
        if (!refresh) return false;
        const res = await this.fetchImpl(`${this.baseUrl}/api/v1/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!res.ok) {
          await this.tokens.setTokens(null);
          this.onSignedOut?.();
          return false;
        }
        await this.tokens.setTokens((await res.json()) as TokenPair);
        return true;
      } finally {
        this.refreshing = null;
      }
    })();
    return this.refreshing;
  }

  // --- core ---------------------------------------------------------------------------

  private async request<T>(method: Method, path: string, opts: RequestOptions<unknown>, retried = false): Promise<T> {
    const url = this.buildUrl(path, opts);
    const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers ?? {}) };
    const token = await this.tokens.getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const org = opts.orgId !== undefined ? opts.orgId : this.orgId;
    if (org && !NO_ORG_PREFIXES.some((p) => path.startsWith(p))) headers["X-Org-Id"] = org;
    const isWrite = method !== "get";
    if (isWrite && !path.startsWith("/api/v1/sync/") && !headers["Idempotency-Key"]) headers["Idempotency-Key"] = this.newKey();
    let body: string | undefined;
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opts.body);
    }
    const res = await this.fetchImpl(url, { method: method.toUpperCase(), headers, body, signal: opts.signal });
    if (res.status === 401 && !retried && !path.startsWith("/api/v1/auth/") && (await this.refresh())) {
      return this.request(method, path, opts, true);
    }
    if (res.status === 204 || res.status === 304) return undefined as T;
    const text = await res.text();
    const data: unknown = text ? JSON.parse(text) : null;
    if (!res.ok) throw new ApiError(res.status, toProblem(res.status, data));
    return data as T;
  }

  private buildUrl(path: string, opts: RequestOptions<unknown>): string {
    let p = path;
    for (const [k, v] of Object.entries((opts.path ?? {}) as Record<string, unknown>)) p = p.replace(`{${k}}`, encodeURIComponent(String(v)));
    const url = new URL(this.baseUrl + p);
    for (const [k, v] of Object.entries((opts.query ?? {}) as Record<string, unknown>)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
    return url.toString();
  }
}

function toProblem(status: number, data: unknown): Problem {
  if (data && typeof data === "object" && "title" in data && "status" in data) return data as Problem;
  return { type: "about:blank", title: `HTTP ${status}`, status, errors: [] };
}
