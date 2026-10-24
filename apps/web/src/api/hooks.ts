import { ApiError } from "@precisecapture/api-client";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
} from "@tanstack/react-query";

import { api } from "./client";

export const keys = {
  me: ["me"] as const,
  org: (id: string) => ["org", id] as const,
  members: (id: string) => ["org", id, "members"] as const,
  invitations: (id: string) => ["org", id, "invitations"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  projectMembers: (id: string) => ["project", id, "members"] as const,
  layers: (projectId: string) => ["project", projectId, "layers"] as const,
  layer: (id: string) => ["layer", id] as const,
  schema: (id: string) => ["layer", id, "schema"] as const,
  versions: (id: string) => ["layer", id, "versions"] as const,
  profile: (id: string) => ["layer", id, "profile"] as const,
  templates: ["templates"] as const,
};

export function useMe(enabled = true) {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => api.get("/api/v1/me"),
    enabled,
    retry: false,
  });
}

export function useOrg(id: string | null) {
  return useQuery({
    queryKey: keys.org(id ?? "none"),
    queryFn: () => api.get("/api/v1/orgs/{org_id}", { path: { org_id: id ?? "" } }),
    enabled: !!id,
  });
}

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: () => api.get("/api/v1/projects") });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: keys.project(id),
    queryFn: () => api.get("/api/v1/projects/{project_id}", { path: { project_id: id } }),
  });
}

export function useLayers(projectId: string) {
  return useQuery({
    queryKey: keys.layers(projectId),
    queryFn: () =>
      api.get("/api/v1/projects/{project_id}/layers", { path: { project_id: projectId } }),
  });
}

export function useLayer(id: string) {
  return useQuery({
    queryKey: keys.layer(id),
    queryFn: () => api.get("/api/v1/layers/{layer_id}", { path: { layer_id: id } }),
  });
}

export function useLayerSchema(id: string) {
  return useQuery({
    queryKey: keys.schema(id),
    queryFn: () => api.get("/api/v1/layers/{layer_id}/schema", { path: { layer_id: id } }),
  });
}

export function useCaptureProfile(id: string) {
  return useQuery({
    queryKey: keys.profile(id),
    queryFn: () => api.get("/api/v1/layers/{layer_id}/capture-profile", { path: { layer_id: id } }),
  });
}

export function useTemplates() {
  return useQuery({ queryKey: keys.templates, queryFn: () => api.get("/api/v1/layer-templates") });
}

/** A mutation that invalidates the given keys on success. */
export function useInvalidatingMutation<TData, TVariables>(
  mutationFn: (vars: TVariables) => Promise<TData>,
  invalidate: readonly (readonly unknown[])[],
  options?: Omit<UseMutationOptions<TData, ApiError, TVariables>, "mutationFn">,
) {
  const qc = useQueryClient();
  return useMutation<TData, ApiError, TVariables>({
    mutationFn,
    ...options,
    onSuccess: async (data, vars, ctx, mutation) => {
      await Promise.all(invalidate.map((k) => qc.invalidateQueries({ queryKey: k })));
      await options?.onSuccess?.(data, vars, ctx, mutation);
    },
  });
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.problem.detail ?? err.problem.title;
  if (err instanceof Error) return err.message;
  return "Unknown error";
}

export function fieldErrors(err: unknown): Record<string, string> {
  return err instanceof ApiError ? err.fieldErrors : {};
}
