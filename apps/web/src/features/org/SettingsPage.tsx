import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { errorMessage, keys, useInvalidatingMutation, useOrg } from "@/api/hooks";
import type { Org } from "@/api/types";
import { useSession } from "@/auth/session";
import { Alert, Button, Card, Field, Input, Spinner } from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { CaptureRulesEditor, type PartialProfile } from "@/features/layers/CaptureRulesEditor";

export function SettingsPage() {
  const { orgId, membership } = useSession();
  const org = useOrg(orgId);
  if (org.isPending) return <Spinner />;
  if (org.isError) return <Alert>{errorMessage(org.error)}</Alert>;
  const canEdit = membership?.role === "owner" || membership?.role === "admin";
  return (
    <div className="space-y-6">
      <OrgForm org={org.data} canEdit={canEdit} />
      <CaptureDefaults org={org.data} canEdit={canEdit} />
    </div>
  );
}

function OrgForm({ org, canEdit }: { org: Org; canEdit: boolean }) {
  const toast = useToast();
  const [name, setName] = useState(org.name);
  const [country, setCountry] = useState(org.country);
  const [slug, setSlug] = useState(org.slug);
  const save = useInvalidatingMutation(
    () =>
      api.patch("/api/v1/orgs/{org_id}", {
        path: { org_id: org.id },
        body: { name, country, slug },
      }),
    [keys.org(org.id), keys.me],
    { onSuccess: () => toast.push("Organisation saved") },
  );
  return (
    <Card title="Organisation">
      <form
        className="grid max-w-xl gap-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(undefined);
        }}
      >
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} disabled={!canEdit} />
        </Field>
        <Field label="Slug" hint="Lowercase letters, digits and dashes">
          <Input value={slug} onChange={(e) => setSlug(e.target.value)} disabled={!canEdit} />
        </Field>
        <Field label="Country (ISO code)">
          <Input
            value={country}
            onChange={(e) => setCountry(e.target.value.toUpperCase())}
            maxLength={2}
            disabled={!canEdit}
          />
        </Field>
        <div className="flex items-end">
          <div className="text-sm text-neutral-600">Plan: {org.plan}</div>
        </div>
        {save.isError && (
          <div className="sm:col-span-2">
            <Alert>{errorMessage(save.error)}</Alert>
          </div>
        )}
        {canEdit && (
          <div className="sm:col-span-2">
            <Button type="submit" disabled={save.isPending}>
              Save
            </Button>
          </div>
        )}
      </form>
    </Card>
  );
}

function CaptureDefaults({ org, canEdit }: { org: Org; canEdit: boolean }) {
  const toast = useToast();
  const initial = (org.settings as { capture_defaults?: PartialProfile }).capture_defaults ?? {};
  const [profile, setProfile] = useState<PartialProfile>(initial);
  useEffect(() => setProfile(initial), [org.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useInvalidatingMutation(
    () =>
      api.patch("/api/v1/orgs/{org_id}", {
        path: { org_id: org.id },
        body: { settings: { ...org.settings, capture_defaults: profile } },
      }),
    [keys.org(org.id)],
    { onSuccess: () => toast.push("Capture defaults saved") },
  );
  return (
    <Card
      title="Capture defaults"
      actions={
        canEdit && (
          <Button onClick={() => save.mutate(undefined)} disabled={save.isPending}>
            Save
          </Button>
        )
      }
    >
      <p className="mb-4 text-sm text-neutral-600">
        Defaults for every layer in this organisation. Projects and layers can override anything
        that is not locked.
      </p>
      <CaptureRulesEditor
        value={profile}
        onChange={setProfile}
        readOnly={!canEdit}
        geometryType={null}
        layerKeys={[]}
      />
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
    </Card>
  );
}
