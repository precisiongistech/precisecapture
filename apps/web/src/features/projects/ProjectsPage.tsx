import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api } from "@/api/client";
import { errorMessage, fieldErrors, keys, useInvalidatingMutation, useProjects } from "@/api/hooks";
import { useSession } from "@/auth/session";
import {
  Alert,
  Badge,
  Button,
  Card,
  Dialog,
  Field,
  Input,
  Spinner,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { AreaMap, type Polygon } from "@/map/AreaMap";

export function ProjectsPage() {
  const projects = useProjects();
  const { membership } = useSession();
  const canCreate = ["owner", "admin", "manager"].includes(membership?.role ?? "");
  if (projects.isPending) return <Spinner />;
  if (projects.isError) return <Alert>{errorMessage(projects.error)}</Alert>;
  return (
    <Card title="Projects" actions={canCreate && <CreateProject />}>
      {projects.data.length === 0 ? (
        <p className="text-sm text-neutral-600">No projects yet.</p>
      ) : (
        <Table
          head={
            <>
              <Th>Name</Th>
              <Th>Status</Th>
              <Th>Layers</Th>
              <Th>Your role</Th>
              <Th>Config</Th>
            </>
          }
        >
          {projects.data.map((p) => (
            <tr key={p.id}>
              <Td>
                <Link
                  to="/projects/$projectId"
                  params={{ projectId: p.id }}
                  className="font-medium text-brand-700 hover:underline"
                >
                  {p.name}
                </Link>
                {p.description && <div className="text-neutral-500">{p.description}</div>}
              </Td>
              <Td>
                <Badge
                  tone={
                    p.status === "active" ? "green" : p.status === "archived" ? "neutral" : "amber"
                  }
                >
                  {p.status}
                </Badge>
              </Td>
              <Td>{p.layer_count}</Td>
              <Td>{p.my_role ?? "—"}</Td>
              <Td className="text-neutral-500">v{p.config_version}</Td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function CreateProject() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [extent, setExtent] = useState<Polygon | null>(null);
  const create = useInvalidatingMutation(
    () =>
      api.post("/api/v1/projects", {
        body: { name, description, extent, status: "active", settings: {} },
      }),
    [keys.projects],
    {
      onSuccess: (p) => void navigate({ to: "/projects/$projectId", params: { projectId: p.id } }),
    },
  );
  const errs = fieldErrors(create.error);
  return (
    <>
      <Button onClick={() => setOpen(true)}>New project</Button>
      <Dialog open={open} onOpenChange={setOpen} title="New project">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate(undefined);
          }}
        >
          <Field label="Name" error={errs.name}>
            <Input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} />
          </Field>
          <Field label="Description">
            <Input value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
          <Field label="Project area (optional)" error={errs.extent}>
            <AreaMap value={extent} onChange={setExtent} height={260} />
          </Field>
          {create.isError && !errs.name && !errs.extent && (
            <Alert>{errorMessage(create.error)}</Alert>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              Create
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
