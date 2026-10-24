import type { TokenPair, TokenStore } from "@precisecapture/api-client";

const KEY = "pc.tokens";
const ORG_KEY = "pc.orgId";

/** Browser token store: localStorage, tolerant of private mode and blocked storage. */
export class LocalTokenStore implements TokenStore {
  private memory: TokenPair | null = null;

  constructor() {
    try {
      const raw = localStorage.getItem(KEY);
      this.memory = raw ? (JSON.parse(raw) as TokenPair) : null;
    } catch {
      this.memory = null;
    }
  }
  getAccessToken(): string | null {
    return this.memory?.access_token ?? null;
  }
  getRefreshToken(): string | null {
    return this.memory?.refresh_token ?? null;
  }
  setTokens(pair: TokenPair | null): void {
    this.memory = pair;
    try {
      if (pair) localStorage.setItem(KEY, JSON.stringify(pair));
      else localStorage.removeItem(KEY);
    } catch {
      /* storage unavailable: keep in memory only */
    }
  }
  get hasSession(): boolean {
    return this.memory !== null;
  }
}

export function loadOrgId(): string | null {
  try {
    return localStorage.getItem(ORG_KEY);
  } catch {
    return null;
  }
}

export function saveOrgId(orgId: string | null): void {
  try {
    if (orgId) localStorage.setItem(ORG_KEY, orgId);
    else localStorage.removeItem(ORG_KEY);
  } catch {
    /* ignore */
  }
}
