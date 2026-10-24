import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "@/api/client";
import {
  errorMessage,
  fieldErrors,
  keys,
  useInvalidatingMutation,
  useLayers,
  useProject,
  useTemplates,
} from "@/api/hooks";
import type { Layer, Project, ProjectMember } from "@/api/types";
import { useSession } from "@/auth/session";
import {
  Alert,
  Badge,
  Button,
  Card,
  Dialog,
  Field,
  Input,
  Select,
  Spinner,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { AreaMap, type AreaGeometry, type Polygon } from "@/map/AreaMap";

export function ProjectPage() {
  const { projectId } = useParams({ from: "/app/projects/$projectId" });
  const project = useProject(projectId);
  if (project.isPending) return <Spinner />;
  if (project.isError) return <Alert>{errorMessage(project.error)}</Alert>;
  const canManage = project.data.my_role === "manager";
  return (
    <div className="space-y-6">
      <ProjectHeader project={project.data} canManage={canManage} />
      <LayersCard project={project.data} canManage={canManage} />
      {canManage && <MembersCard project={project.data} />}
    </div>
  );
}

function ProjectHeader({ project, canManage }: { project: Project; canManage: boolean }) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description);
  const [status, setStatus] = useState(project.status);
  const [extent, setExtent] = useState<Polygon | null>((project.extent as Polygon | null) ?? null);
  const save = useInvalidatingMutation(
    () =>
      api.patch("/api/v1/projects/{project_id}", {
        path: { project_id: project.id },
        body: { name, description, status, extent },
      }),
    [keys.project(project.id), keys.projects],
    {
      onSuccess: () => {
        toast.push("Project saved");
        setEditing(false);
      },
    },
  );
  return (
    <Card
      title={project.name}
      actions={
        canManage && (
          <Button variant="secondary" onClick={() => setEditing(true)}>
            Edit
          </Button>
        )
      }
    >
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2 text-sm">
          <div>
            <Badge tone={project.status === "active" ? "green" : "amber"}>{project.status}</Badge>
            <span className="ml-2 text-neutral-500">config v{project.config_version}</span>
          </div>
          {project.description && <p className="text-neutral-700">{project.description}</p>}
          <p className="text-neutral-500">Your role: {project.my_role ?? "—"}</p>
        </div>
        <AreaMap value={(project.extent as AreaGeometry | null) ?? null} readOnly height={220} />
      </div>
      <Dialog open={editing} onOpenChange={setEditing} title="Edit project">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(undefined);
          }}
        >
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} />
          </Field>
          <Field label="Description">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <Field label="Status">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="draft">draft</option>
              <option value="active">active</option>
              <option value="archived">archived</option>
            </Select>
          </Field>
          <Field label="Project area">
            <AreaMap value={extent} onChange={setExtent} height={240} />
          </Field>
          {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending}>
              Save
            </Button>
          </div>
        </form>
      </Dialog>
    </Card>
  );
}

function LayersCard({ project, canManage }: { project: Project; canManage: boolean }) {
  const layers = useLayers(project.id);
  if (layers.isPending) return <Spinner />;
  if (layers.isError) return <Alert>{errorMessage(layers.error)}</Alert>;
  return (
    <Card
      title="Layers"
      actions={canManage && <AddLayer project={project} existing={layers.data} />}
    >
      {layers.data.length === 0 ? (
        <p className="text-sm text-neutral-600">
          No layers yet. A layer is one feature type with its own form and capture rules.
        </p>
      ) : (
        <Table
          head={
            <>
              <Th>Layer</Th>
              <Th>Key</Th>
              <Th>Geometry</Th>
              <Th>Schema</Th>
            </>
          }
        >
          {layers.data.map((l) => (
            <tr key={l.id}>
              <Td>
                <Link
                  to="/layers/$layerId"
                  params={{ layerId: l.id }}
                  className="font-medium text-brand-700 hover:underline"
                >
                  {l.name}
                </Link>
              </Td>
              <Td className="font-mono text-xs">{l.key}</Td>
              <Td>{l.geometry_type}</Td>
              <Td>
                {l.current_schema_version === 0 ? (
                  <Badge tone="amber">unpublished</Badge>
                ) : (
                  <Badge tone="green">v{l.current_schema_version}</Badge>
                )}
                {l.has_draft && <Badge tone="blue">draft</Badge>}
              </Td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function slugify(name: string): string {
  const base = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 50);
  return base ? `lyr_${base}` : "";
}

function AddLayer({ project, existing }: { project: Project; existing: Layer[] }) {
  const toast = useToast();
  const templates = useTemplates();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [geometryType, setGeometryType] = useState("polygon");
  const [templateId, setTemplateId] = useState("");
  const create = useInvalidatingMutation(
    () =>
      templateId
        ? api.post("/api/v1/projects/{project_id}/layers/from-template", {
            path: { project_id: project.id },
            body: { template_id: templateId, name, key },
          })
        : api.post("/api/v1/projects/{project_id}/layers", {
            path: { project_id: project.id },
            body: { name, key, geometry_type: geometryType, style: {}, capture_profile: {} },
          }),
    [keys.layers(project.id), keys.project(project.id), keys.projects],
    {
      onSuccess: () => {
        toast.push("Layer created");
        setOpen(false);
        setName("");
        setKey("");
        setTemplateId("");
      },
    },
  );
  const errs = fieldErrors(create.error);
  const keyTaken = existing.some((l) => l.key === key);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Add layer</Button>
      <Dialog open={open} onOpenChange={setOpen} title="Add layer">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!keyTaken) create.mutate(undefined);
          }}
        >
          <Field label="Name" error={errs.name}>
            <Input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setKey(slugify(e.target.value));
              }}
              required
            />
          </Field>
          <Field
            label="Key"
            hint="Used inside schemas and capture rules; cannot change later"
            error={keyTaken ? "This key is already used in the project" : errs.key}
          >
            <Input
              value={key}
              onChange={(e) => setKey(e.target.value)}
              pattern="^[a-z][a-z0-9_]{0,62}$"
              required
            />
          </Field>
          {templates.data && templates.data.length > 0 && (
            <Field label="Start from a template">
              <Select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                <option value="">— blank layer —</option>
                {templates.data.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.geometry_type})
                  </option>
                ))}
              </Select>
            </Field>
          )}
          {!templateId && (
            <Field label="Geometry" hint="Cannot change once features exist">
              <Select value={geometryType} onChange={(e) => setGeometryType(e.target.value)}>
                <option value="point">Point</option>
                <option value="line">Line</option>
                <option value="polygon">Polygon</option>
                <option value="none">No geometry (table)</option>
              </Select>
            </Field>
          )}
          {create.isError && !errs.name && !errs.key && <Alert>{errorMessage(create.error)}</Alert>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending || keyTaken}>
              Create
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

function MembersCard({ project }: { project: Project }) {
  const { orgId } = useSession();
  const toast = useToast();
  const members = useQuery({
    queryKey: keys.projectMembers(project.id),
    queryFn: () =>
      api.get("/api/v1/projects/{project_id}/members", { path: { project_id: project.id } }),
  });
  const orgMembers = useQuery({
    queryKey: keys.members(orgId ?? ""),
    queryFn: () => api.get("/api/v1/orgs/{org_id}/members", { path: { org_id: orgId ?? "" } }),
    enabled: !!orgId,
  });
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("collector");
  const add = useInvalidatingMutation(
    () =>
      api.post("/api/v1/projects/{project_id}/members", {
        path: { project_id: project.id },
        body: { user_id: userId, role, assigned_area: null },
      }),
    [keys.projectMembers(project.id), keys.project(project.id)],
    {
      onSuccess: () => toast.push("Member added"),
      onError: (e) => toast.push(errorMessage(e), "error"),
    },
  );
  if (members.isPending) return <Spinner />;
  if (members.isError) return <Alert>{errorMessage(members.error)}</Alert>;
  const candidates = (orgMembers.data ?? []).filter(
    (m) => !members.data.some((pm) => pm.user_id === m.user_id),
  );
  return (
    <Card title="Project members">
      <p className="mb-3 text-sm text-neutral-600">
        Org owners, admins and managers manage every project. Add collectors and viewers here.
      </p>
      <Table
        head={
          <>
            <Th>Name</Th>
            <Th>Role</Th>
            <Th>Assigned area</Th>
            <Th />
          </>
        }
      >
        {members.data.map((m) => (
          <ProjectMemberRow key={m.user_id} member={m} project={project} />
        ))}
      </Table>
      {candidates.length > 0 && (
        <form
          className="mt-4 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (userId) add.mutate(undefined);
          }}
        >
          <Field label="Add member">
            <Select value={userId} onChange={(e) => setUserId(e.target.value)} required>
              <option value="">— choose —</option>
              {candidates.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.name || m.email || m.phone}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Role">
            <Select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="manager">manager</option>
              <option value="collector">collector</option>
              <option value="viewer">viewer</option>
            </Select>
          </Field>
          <Button type="submit" disabled={!userId || add.isPending}>
            Add
          </Button>
        </form>
      )}
    </Card>
  );
}

function ProjectMemberRow({ member, project }: { member: ProjectMember; project: Project }) {
  const toast = useToast();
  const [areaOpen, setAreaOpen] = useState(false);
  const [area, setArea] = useState<Polygon | null>(null);
  const update = useInvalidatingMutation(
    (body: { role?: string; assigned_area?: Polygon | null; clear_assigned_area?: boolean }) =>
      api.patch("/api/v1/projects/{project_id}/members/{user_id}", {
        path: { project_id: project.id, user_id: member.user_id },
        body: { clear_assigned_area: false, ...body },
      }),
    [keys.projectMembers(project.id), keys.project(project.id)],
    { onSuccess: () => setAreaOpen(false), onError: (e) => toast.push(errorMessage(e), "error") },
  );
  const remove = useInvalidatingMutation(
    () =>
      api.delete("/api/v1/projects/{project_id}/members/{user_id}", {
        path: { project_id: project.id, user_id: member.user_id },
      }),
    [keys.projectMembers(project.id), keys.project(project.id)],
  );
  return (
    <tr>
      <Td>
        {member.name || member.email || member.phone}
        <div className="text-neutral-500">{member.email}</div>
      </Td>
      <Td>
        <Select
          value={member.role}
          onChange={(e) => update.mutate({ role: e.target.value })}
          aria-label={`Project role of ${member.name}`}
        >
          <option value="manager">manager</option>
          <option value="collector">collector</option>
          <option value="viewer">viewer</option>
        </Select>
      </Td>
      <Td>
        {member.assigned_area ? (
          <Badge tone="blue">set</Badge>
        ) : (
          <span className="text-neutral-400">whole project</span>
        )}
        <Button variant="ghost" size="sm" className="ml-2" onClick={() => setAreaOpen(true)}>
          Edit
        </Button>
        <Dialog open={areaOpen} onOpenChange={setAreaOpen} title="Assigned area">
          <AreaMap
            value={area ?? (member.assigned_area as AreaGeometry | null) ?? null}
            onChange={setArea}
            height={300}
          />
          <div className="mt-3 flex justify-end gap-2">
            {member.assigned_area && (
              <Button variant="ghost" onClick={() => update.mutate({ clear_assigned_area: true })}>
                Clear
              </Button>
            )}
            <Button variant="secondary" onClick={() => setAreaOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => area && update.mutate({ assigned_area: area })} disabled={!area}>
              Save
            </Button>
          </div>
        </Dialog>
      </Td>
      <Td>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => confirm("Remove from project?") && remove.mutate(undefined)}
        >
          Remove
        </Button>
      </Td>
    </tr>
  );
}
