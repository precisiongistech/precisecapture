import { beforeEach, describe, expect, it } from "vitest";

import { LocalTokenStore, loadOrgId, saveOrgId } from "./tokens";

const pair = { access_token: "a", refresh_token: "r", token_type: "Bearer", expires_in: 900 };

describe("LocalTokenStore", () => {
  beforeEach(() => localStorage.clear());

  it("persists tokens and reloads them", () => {
    const store = new LocalTokenStore();
    expect(store.hasSession).toBe(false);
    store.setTokens(pair);
    expect(new LocalTokenStore().getAccessToken()).toBe("a");
    expect(new LocalTokenStore().hasSession).toBe(true);
    store.setTokens(null);
    expect(new LocalTokenStore().getRefreshToken()).toBeNull();
  });

  it("remembers the selected organisation", () => {
    saveOrgId("org-1");
    expect(loadOrgId()).toBe("org-1");
    saveOrgId(null);
    expect(loadOrgId()).toBeNull();
  });
});
