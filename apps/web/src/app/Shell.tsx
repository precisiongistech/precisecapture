import { Link, Outlet, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "@/api/client";
import { useSession } from "@/auth/session";
import { Button, Select, Spinner } from "@/components/ui";
import { t } from "@/lib/strings";

const nav = [
  { to: "/projects", label: t.nav.projects },
  { to: "/data", label: t.nav.data },
  { to: "/members", label: t.nav.members },
  { to: "/settings", label: t.nav.settings },
] as const;

export function Shell() {
  const { me, membership, orgId, setOrgId, signOut, loading } = useSession();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  if (loading || !me) return <Spinner />;
  if (me.memberships.length === 0) return <NoOrg />;
  return (
    <div className="flex min-h-full">
      <aside
        className={
          "fixed inset-y-0 left-0 z-40 w-60 transform border-r border-neutral-200 bg-white transition md:static md:translate-x-0 " +
          (open ? "translate-x-0" : "-translate-x-full")
        }
      >
        <div className="border-b border-neutral-200 p-4">
          <div className="text-lg font-semibold text-brand-700">{t.appName}</div>
          <label className="mt-3 block text-xs text-neutral-500">
            Organisation
            <Select
              className="mt-1"
              value={orgId ?? ""}
              onChange={(e) => {
                setOrgId(e.target.value);
                void navigate({ to: "/projects" });
              }}
              aria-label="Organisation"
            >
              {me.memberships.map((m) => (
                <option key={m.org_id} value={m.org_id}>
                  {m.org_name}
                </option>
              ))}
            </Select>
          </label>
        </div>
        <nav className="space-y-1 p-2">
          {nav.map((n) => (
            <Link
              key={n.to}
              to={n.to}
              onClick={() => setOpen(false)}
              className="block rounded-md px-3 py-2 text-sm text-neutral-700 hover:bg-neutral-100"
              activeProps={{
                className:
                  "block rounded-md px-3 py-2 text-sm bg-brand-50 text-brand-700 font-medium",
              }}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="absolute bottom-0 w-full border-t border-neutral-200 p-3 text-sm">
          <div className="truncate text-neutral-700">
            {me.user.name || me.user.email || me.user.phone}
          </div>
          <div className="text-xs text-neutral-500">{membership?.role}</div>
          <Button variant="ghost" size="sm" className="mt-2 w-full" onClick={() => void signOut()}>
            {t.nav.signOut}
          </Button>
        </div>
      </aside>
      <div className="flex-1">
        <header className="flex items-center gap-3 border-b border-neutral-200 bg-white px-4 py-2 md:hidden">
          <Button variant="ghost" size="sm" onClick={() => setOpen(!open)} aria-label="Menu">
            ☰
          </Button>
          <span className="font-semibold">{t.appName}</span>
        </header>
        <main className="mx-auto max-w-6xl p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function NoOrg() {
  const { afterLogin, signOut } = useSession();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="text-lg font-semibold">{t.common.noOrg}</h1>
      <form
        className="mt-4 flex gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          await api.post("/api/v1/orgs", { body: { name, country: "", settings: {} } });
          await afterLogin();
          setBusy(false);
          await navigate({ to: "/projects" });
        }}
      >
        <input
          className="flex-1 rounded-md border border-neutral-300 px-3 py-2 text-sm"
          placeholder="Organisation name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          minLength={2}
        />
        <Button type="submit" disabled={busy}>
          {t.common.createOrg}
        </Button>
      </form>
      <Button variant="ghost" className="mt-6" onClick={() => void signOut()}>
        {t.nav.signOut}
      </Button>
    </main>
  );
}
