import { PreciseCaptureClient } from "@precisecapture/api-client";

import { LocalTokenStore, loadOrgId } from "./tokens";

export const tokenStore = new LocalTokenStore();

type Listener = () => void;
const listeners = new Set<Listener>();

export const api = new PreciseCaptureClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  tokens: tokenStore,
  orgId: loadOrgId(),
  onSignedOut: () => listeners.forEach((l) => l()),
});

/** Subscribe to forced sign-outs (refresh failed). Returns an unsubscribe function. */
export function onSignedOut(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
