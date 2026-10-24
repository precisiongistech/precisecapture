import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, onSignedOut, tokenStore } from "@/api/client";
import { useMe } from "@/api/hooks";
import { saveOrgId } from "@/api/tokens";
import type { Me, Membership } from "@/api/types";

type Session = {
  me: Me | null;
  loading: boolean;
  signedIn: boolean;
  orgId: string | null;
  membership: Membership | null;
  setOrgId: (id: string) => void;
  signOut: () => Promise<void>;
  afterLogin: () => Promise<void>;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState<boolean>(tokenStore.hasSession);
  const [orgId, setOrg] = useState<string | null>(api.orgId);
  const me = useMe(signedIn);

  useEffect(() => onSignedOut(() => setSignedIn(false)), []);

  // Pick an org once memberships are known and none is selected (or the selection is stale).
  useEffect(() => {
    const memberships = me.data?.memberships ?? [];
    if (memberships.length === 0) return;
    if (!orgId || !memberships.some((m) => m.org_id === orgId)) {
      const first = memberships[0]!.org_id;
      api.orgId = first;
      saveOrgId(first);
      setOrg(first);
    }
  }, [me.data, orgId]);

  const setOrgId = useCallback(
    (id: string) => {
      api.orgId = id;
      saveOrgId(id);
      setOrg(id);
      void qc.invalidateQueries();
    },
    [qc],
  );

  const signOut = useCallback(async () => {
    await api.logout();
    setSignedIn(false);
    qc.clear();
  }, [qc]);

  const afterLogin = useCallback(async () => {
    setSignedIn(true);
    await qc.invalidateQueries({ queryKey: ["me"] });
  }, [qc]);

  const value = useMemo<Session>(
    () => ({
      me: me.data ?? null,
      loading: signedIn && me.isPending,
      signedIn: signedIn && !me.isError,
      orgId,
      membership: me.data?.memberships.find((m) => m.org_id === orgId) ?? null,
      setOrgId,
      signOut,
      afterLogin,
    }),
    [me.data, me.isPending, me.isError, signedIn, orgId, setOrgId, signOut, afterLogin],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside SessionProvider");
  return ctx;
}
