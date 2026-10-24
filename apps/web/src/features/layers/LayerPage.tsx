import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import {
  errorMessage,
  fieldErrors,
  keys,
  useCaptureProfile,
  useInvalidatingMutation,
  useLayer,
  useLayerSchema,
  useLayers,
} from "@/api/hooks";
import type { Layer } from "@/api/types";
import {
  Alert,
  Badge,
  Button,
  Card,
  Dialog,
  Field,
  Input,
  Spinner,
  Tab,
  TabList,
  TabPanel,
  Tabs,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import {
  AttributeBuilder,
  type FieldDef,
  type SchemaDoc,
} from "@/features/layers/AttributeBuilder";
import { CaptureRulesEditor, type PartialProfile } from "@/features/layers/CaptureRulesEditor";
import { ImportJson } from "@/components/ImportJson";
import { FormPreview } from "@/features/layers/FormPreview";

export function LayerPage() {
  const { layerId } = useParams({ from: "/app/layers/$layerId" });
  const layer = useLayer(layerId);
  if (layer.isPending) return <Spinner />;
  if (layer.isError) return <Alert>{errorMessage(layer.error)}</Alert>;
  return <LayerScreen layer={layer.data} />;
}

function LayerScreen({ layer }: { layer: Layer }) {
  const layers = useLayers(layer.project_id);
  const layerKeys = (layers.data ?? []).map((l) => l.key);
  return (
    <div className="space-y-4">
      <div className="text-sm text-neutral-500">
        <Link
          to="/projects/$projectId"
          params={{ projectId: layer.project_id }}
          className="hover:underline"
        >
          ← Project
        </Link>
      </div>
      <h1 className="text-xl font-semibold">
        {layer.name} <span className="font-mono text-sm text-neutral-500">{layer.key}</span>{" "}
        <Badge>{layer.geometry_type}</Badge>{" "}
        {layer.current_schema_version === 0 ? (
          <Badge tone="amber">unpublished</Badge>
        ) : (
          <Badge tone="green">schema v{layer.current_schema_version}</Badge>
        )}
      </h1>
      <Tabs defaultValue="attributes">
        <TabList>
          <Tab value="general">General</Tab>
          <Tab value="attributes">Attributes</Tab>
          <Tab value="rules">Capture rules</Tab>
          <Tab value="publish">Publish</Tab>
        </TabList>
        <TabPanel value="general">
          <GeneralTab layer={layer} />
        </TabPanel>
        <TabPanel value="attributes">
          <AttributesTab layer={layer} layerKeys={layerKeys} />
        </TabPanel>
        <TabPanel value="rules">
          <RulesTab layer={layer} layerKeys={layerKeys} />
        </TabPanel>
        <TabPanel value="publish">
          <PublishTab layer={layer} layerKeys={layerKeys} />
        </TabPanel>
      </Tabs>
    </div>
  );
}

// --- General ------------------------------------------------------------------------------

function GeneralTab({ layer }: { layer: Layer }) {
  const toast = useToast();
  const [name, setName] = useState(layer.name);
  const [style, setStyle] = useState(JSON.stringify(layer.style, null, 2));
  const [styleError, setStyleError] = useState<string | null>(null);
  const save = useInvalidatingMutation(
    () => {
      let parsed: Record<string, unknown> = {};
      try {
        parsed = style.trim() ? (JSON.parse(style) as Record<string, unknown>) : {};
      } catch {
        setStyleError("Style must be valid JSON");
        return Promise.reject(new Error("Style must be valid JSON"));
      }
      setStyleError(null);
      return api.patch("/api/v1/layers/{layer_id}", {
        path: { layer_id: layer.id },
        body: { name, style: parsed },
      });
    },
    [keys.layer(layer.id), keys.layers(layer.project_id)],
    { onSuccess: () => toast.push("Layer saved") },
  );
  const remove = useInvalidatingMutation(
    () => api.delete("/api/v1/layers/{layer_id}", { path: { layer_id: layer.id } }),
    [keys.layers(layer.project_id), keys.project(layer.project_id)],
    {
      onSuccess: () => {
        toast.push("Layer deleted");
        history.back();
      },
      onError: (e) => toast.push(errorMessage(e), "error"),
    },
  );
  return (
    <Card>
      <form
        className="max-w-xl space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate(undefined);
        }}
      >
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field label="Key" hint="Fixed: referenced by other layers' schemas and capture rules">
          <Input value={layer.key} disabled />
        </Field>
        <Field label="Geometry" hint="Fixed once features exist">
          <Input value={layer.geometry_type} disabled />
        </Field>
        <Field
          label="Style (JSON)"
          error={styleError ?? undefined}
          hint='e.g. {"fill": "#1f9d55", "stroke": "#136236", "pointRadius": 6}'
        >
          <textarea
            className="w-full rounded-md border border-neutral-300 p-2 font-mono text-xs"
            rows={5}
            value={style}
            onChange={(e) => setStyle(e.target.value)}
          />
        </Field>
        {save.isError && !styleError && <Alert>{errorMessage(save.error)}</Alert>}
        <div className="flex items-center justify-between">
          <Button type="submit" disabled={save.isPending}>
            Save
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={() =>
              confirm("Delete this layer? Only possible while it has no features.") &&
              remove.mutate(undefined)
            }
          >
            Delete layer
          </Button>
        </div>
      </form>
    </Card>
  );
}

// --- Attributes --------------------------------------------------------------------------------

const EMPTY: SchemaDoc = { fields: [], lists: {} };

function useDraft(layer: Layer) {
  const schema = useLayerSchema(layer.id);
  const [draft, setDraft] = useState<SchemaDoc | null>(null);
  useEffect(() => {
    if (schema.data && draft === null) {
      const base = (schema.data.draft ?? schema.data.current ?? EMPTY) as SchemaDoc;
      setDraft({
        fields: base.fields ?? [],
        lists: base.lists ?? {},
        title: base.title ?? { en: layer.name },
      });
    }
  }, [schema.data, draft, layer.name]);
  const dirty = useMemo(() => {
    if (!schema.data || !draft) return false;
    const stored = (schema.data.draft ?? schema.data.current) as SchemaDoc | null;
    return JSON.stringify(strip(stored)) !== JSON.stringify(strip(draft));
  }, [schema.data, draft]);
  return { schema, draft, setDraft, dirty };
}

function strip(doc: SchemaDoc | null): unknown {
  if (!doc) return null;
  return { fields: doc.fields, lists: doc.lists ?? {}, title: doc.title };
}

function AttributesTab({ layer, layerKeys }: { layer: Layer; layerKeys: string[] }) {
  const toast = useToast();
  const { schema, draft, setDraft, dirty } = useDraft(layer);
  const save = useInvalidatingMutation(
    () =>
      api.put("/api/v1/layers/{layer_id}/schema", {
        path: { layer_id: layer.id },
        body: { attributes: draft ?? EMPTY },
      }),
    [keys.schema(layer.id), keys.layer(layer.id), keys.layers(layer.project_id)],
    { onSuccess: () => toast.push("Draft saved") },
  );
  if (schema.isPending || !draft) return <Spinner />;
  if (schema.isError) return <Alert>{errorMessage(schema.error)}</Alert>;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <Card
        title="Attributes (the form)"
        actions={
          <>
            {dirty && <Badge tone="amber">unsaved</Badge>}
            <ImportJson
              label="Schema JSON"
              onImport={(doc) =>
                setDraft({
                  fields: (doc.fields as FieldDef[]) ?? [],
                  lists: (doc.lists as SchemaDoc["lists"]) ?? {},
                  title: (doc.title as SchemaDoc["title"]) ?? draft.title,
                })
              }
            />
            <Button onClick={() => save.mutate(undefined)} disabled={save.isPending || !dirty}>
              Save draft
            </Button>
          </>
        }
      >
        <AttributeBuilder
          value={draft}
          onChange={setDraft}
          layerKeys={layerKeys.filter((k) => k !== layer.key).concat(layer.key)}
        />
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
      </Card>
      <Card title="Phone preview">
        <FormPreview schema={draft} geometryType={layer.geometry_type} />
      </Card>
    </div>
  );
}

// --- Capture rules ----------------------------------------------------------------------------------

function RulesTab({ layer, layerKeys }: { layer: Layer; layerKeys: string[] }) {
  const toast = useToast();
  const profile = useCaptureProfile(layer.id);
  const [value, setValue] = useState<PartialProfile | null>(null);
  useEffect(() => {
    if (profile.data && value === null) setValue(profile.data.capture_profile as PartialProfile);
  }, [profile.data, value]);
  const save = useInvalidatingMutation(
    () =>
      api.put("/api/v1/layers/{layer_id}/capture-profile", {
        path: { layer_id: layer.id },
        body: { capture_profile: value ?? {} },
      }),
    [
      keys.profile(layer.id),
      keys.layer(layer.id),
      keys.layers(layer.project_id),
      keys.project(layer.project_id),
    ],
    { onSuccess: () => toast.push("Capture rules saved") },
  );
  if (profile.isPending || !value) return <Spinner />;
  if (profile.isError) return <Alert>{errorMessage(profile.error)}</Alert>;
  const errs = fieldErrors(save.error);
  return (
    <Card
      title="Capture rules"
      actions={
        <>
          <ImportJson
            label="Capture profile JSON"
            onImport={(doc) => setValue(doc as PartialProfile)}
          />
          <Button onClick={() => save.mutate(undefined)} disabled={save.isPending}>
            Save
          </Button>
        </>
      }
    >
      <p className="mb-3 text-sm text-neutral-600">
        Values left as "inherit" come from the project or organisation defaults (shown in grey). A
        lock stops collectors changing that group of settings on the phone.
      </p>
      <CaptureRulesEditor
        value={value}
        onChange={setValue}
        geometryType={layer.geometry_type}
        layerKeys={layerKeys.filter((k) => k !== layer.key)}
        resolved={profile.data.resolved as PartialProfile}
      />
      {save.isError && (
        <Alert>
          {Object.keys(errs).length ? (
            <ul className="list-disc pl-4">
              {Object.entries(errs).map(([f, m]) => (
                <li key={f}>
                  <span className="font-mono text-xs">{f}</span>: {m}
                </li>
              ))}
            </ul>
          ) : (
            errorMessage(save.error)
          )}
        </Alert>
      )}
    </Card>
  );
}

// --- Publish ------------------------------------------------------------------------------------------

type DryRun = { errors: Array<{ field?: string | null; code: string; message: string }> };

function PublishTab({ layer, layerKeys }: { layer: Layer; layerKeys: string[] }) {
  const toast = useToast();
  const schema = useLayerSchema(layer.id);
  const draft = (schema.data?.draft ?? null) as SchemaDoc | null;
  const current = (schema.data?.current ?? null) as SchemaDoc | null;
  const dryRun = useQuery({
    queryKey: [...keys.schema(layer.id), "validate", JSON.stringify(draft)],
    queryFn: () =>
      api.post("/api/v1/layers/{layer_id}/schema/validate", {
        path: { layer_id: layer.id },
        body: { attributes: draft ?? EMPTY },
      }) as Promise<DryRun>,
    enabled: !!draft,
  });
  const publish = useInvalidatingMutation(
    () => api.post("/api/v1/layers/{layer_id}/schema/publish", { path: { layer_id: layer.id } }),
    [
      keys.schema(layer.id),
      keys.layer(layer.id),
      keys.layers(layer.project_id),
      keys.project(layer.project_id),
    ],
    {
      onSuccess: (r) =>
        toast.push(
          `Published version ${r.version}` +
            (r.warnings.length
              ? ` (${r.warnings.length} warning${r.warnings.length > 1 ? "s" : ""})`
              : ""),
        ),
    },
  );
  if (schema.isPending) return <Spinner />;
  if (schema.isError) return <Alert>{errorMessage(schema.error)}</Alert>;
  const diff = diffSchemas(current, draft);
  const errors = dryRun.data?.errors ?? [];
  const canPublish =
    !!draft &&
    errors.length === 0 &&
    (diff.added.length + diff.removed.length + diff.changed.length > 0 || !current);
  return (
    <div className="space-y-4">
      <Card
        title={`Changes since ${current ? `version ${schema.data.current_version}` : "the start"}`}
        actions={<SaveAsTemplate layer={layer} disabled={!current && !draft} />}
      >
        {!draft ? (
          <p className="text-sm text-neutral-600">
            No draft. Edit the attributes and save a draft first.
          </p>
        ) : (
          <ul className="space-y-1 text-sm">
            {diff.added.map((k) => (
              <li key={`a${k}`}>
                <Badge tone="green">added</Badge> <span className="font-mono">{k}</span>
              </li>
            ))}
            {diff.removed.map((k) => (
              <li key={`r${k}`}>
                <Badge tone="amber">removed</Badge> <span className="font-mono">{k}</span>{" "}
                <span className="text-neutral-500">(existing data keeps it)</span>
              </li>
            ))}
            {diff.changed.map((c) => (
              <li key={`c${c.key}`}>
                <Badge tone={c.breaking ? "red" : "blue"}>
                  {c.breaking ? "type change" : "changed"}
                </Badge>{" "}
                <span className="font-mono">{c.key}</span>{" "}
                <span className="text-neutral-500">{c.detail}</span>
              </li>
            ))}
            {diff.added.length + diff.removed.length + diff.changed.length === 0 && (
              <li className="text-neutral-500">The draft is identical to the current version.</li>
            )}
          </ul>
        )}
      </Card>
      {draft && (
        <Card title="Server check">
          {dryRun.isPending ? (
            <Spinner label="Validating…" />
          ) : errors.length === 0 ? (
            <Alert tone="success">
              No problems found. Publishing creates version {schema.data.current_version + 1} and
              updates every phone's configuration.
            </Alert>
          ) : (
            <Alert>
              <ul className="list-disc pl-4">
                {errors.map((e, i) => (
                  <li key={i}>
                    <span className="font-mono text-xs">{e.field}</span>{" "}
                    <Badge tone="red">{e.code}</Badge> {e.message}
                  </li>
                ))}
              </ul>
            </Alert>
          )}
          <div className="mt-3 flex items-center gap-3">
            <Button
              onClick={() => publish.mutate(undefined)}
              disabled={!canPublish || publish.isPending}
            >
              Publish version {schema.data.current_version + 1}
            </Button>
            {publish.isError && (
              <span className="text-sm text-red-600">{errorMessage(publish.error)}</span>
            )}
            {publish.data?.warnings.map((w) => (
              <Alert key={w} tone="info">
                {w}
              </Alert>
            ))}
          </div>
        </Card>
      )}
      <Card title="Published versions">
        <Versions layerId={layer.id} />
      </Card>
      <p className="hidden">{layerKeys.length}</p>
    </div>
  );
}

const SAFE: Record<string, string[]> = {
  integer: ["number", "decimal"],
  decimal: ["number"],
  number: ["decimal"],
  select_one: ["select_many"],
  phone: ["text"],
  email: ["text"],
  barcode: ["text"],
  date: ["datetime"],
};

function flat(doc: SchemaDoc | null): Record<string, FieldDef> {
  const out: Record<string, FieldDef> = {};
  const walk = (fields: FieldDef[], prefix: string) => {
    for (const f of fields) {
      out[prefix + f.key] = f;
      if (f.fields) walk(f.fields, `${prefix}${f.key}.`);
    }
  };
  if (doc) walk(doc.fields, "");
  return out;
}

export function diffSchemas(current: SchemaDoc | null, draft: SchemaDoc | null) {
  const a = flat(current);
  const b = flat(draft);
  const added = Object.keys(b).filter((k) => !(k in a));
  const removed = Object.keys(a).filter((k) => !(k in b));
  const changed: Array<{ key: string; detail: string; breaking: boolean }> = [];
  for (const k of Object.keys(b).filter((k) => k in a)) {
    const x = a[k]!;
    const y = b[k]!;
    if (x.type !== y.type) {
      const safe = (SAFE[x.type] ?? []).includes(y.type);
      changed.push({
        key: k,
        detail: `${x.type} → ${y.type}${safe ? "" : " (breaks collected data; will be rejected)"}`,
        breaking: !safe,
      });
    } else if (JSON.stringify(x) !== JSON.stringify(y)) {
      const parts: string[] = [];
      if (x.required !== y.required)
        parts.push(y.required ? "now required (new captures only)" : "no longer required");
      if (JSON.stringify(x.options) !== JSON.stringify(y.options)) parts.push("options changed");
      if (
        x.relevant !== y.relevant ||
        x.constraint !== y.constraint ||
        x.expression !== y.expression
      )
        parts.push("rules changed");
      if (JSON.stringify(x.label) !== JSON.stringify(y.label)) parts.push("label changed");
      changed.push({ key: k, detail: parts.join(", ") || "edited", breaking: false });
    }
  }
  return { added, removed, changed };
}

function Versions({ layerId }: { layerId: string }) {
  const versions = useQuery({
    queryKey: keys.versions(layerId),
    queryFn: () =>
      api.get("/api/v1/layers/{layer_id}/schema/versions", { path: { layer_id: layerId } }),
  });
  if (versions.isPending) return <Spinner />;
  if (versions.isError) return <Alert>{errorMessage(versions.error)}</Alert>;
  if (versions.data.length === 0)
    return <p className="text-sm text-neutral-600">Nothing published yet.</p>;
  return (
    <ul className="text-sm">
      {[...versions.data].reverse().map((v) => (
        <li key={v.version} className="flex gap-3 border-b border-neutral-100 py-1">
          <Badge tone="green">v{v.version}</Badge>
          <span className="text-neutral-600">{new Date(v.published_at).toLocaleString()}</span>
          <span className="text-neutral-500">
            {((v.attributes as SchemaDoc).fields ?? []).length} attributes
          </span>
        </li>
      ))}
    </ul>
  );
}

function SaveAsTemplate({ layer, disabled }: { layer: Layer; disabled: boolean }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(`${layer.name} template`);
  const [description, setDescription] = useState("");
  const save = useInvalidatingMutation(
    () =>
      api.post("/api/v1/layers/{layer_id}/save-as-template", {
        path: { layer_id: layer.id },
        body: { name, description },
      }),
    [keys.templates],
    {
      onSuccess: () => {
        toast.push("Template saved");
        setOpen(false);
      },
    },
  );
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)} disabled={disabled}>
        Save as template
      </Button>
      <Dialog open={open} onOpenChange={setOpen} title="Save layer as template">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(undefined);
          }}
        >
          <Field label="Template name">
            <Input value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
          <Field label="Description">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              Save
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
