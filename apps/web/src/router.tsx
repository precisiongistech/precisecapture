import { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Navigate,
  Outlet,
  redirect,
} from "@tanstack/react-router";

import { tokenStore } from "@/api/client";
import { ErrorView } from "@/app/ErrorView";
import { Shell } from "@/app/Shell";
import { LoginPage } from "@/auth/LoginPage";
import { DataPage } from "@/features/data/DataPage";
import { LayerPage } from "@/features/layers/LayerPage";
import { MembersPage } from "@/features/org/MembersPage";
import { SettingsPage } from "@/features/org/SettingsPage";
import { ProjectPage } from "@/features/projects/ProjectPage";
import { ProjectsPage } from "@/features/projects/ProjectsPage";

export type RouterContext = { queryClient: QueryClient };

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: () => <Outlet />,
  errorComponent: ({ error, reset }) => <ErrorView error={error} reset={reset} />,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  component: LoginPage,
});

const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  beforeLoad: () => {
    if (!tokenStore.hasSession) throw redirect({ to: "/login" });
  },
  component: Shell,
});

const indexRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/",
  component: () => <Navigate to="/projects" />,
});
const projectsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/projects",
  component: ProjectsPage,
});
const projectRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/projects/$projectId",
  component: ProjectPage,
});
const layerRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/layers/$layerId",
  component: LayerPage,
});
const dataRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/data",
  component: DataPage,
});
const membersRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/members",
  component: MembersPage,
});
const settingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/settings",
  component: SettingsPage,
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  appRoute.addChildren([
    indexRoute,
    projectsRoute,
    projectRoute,
    layerRoute,
    dataRoute,
    membersRoute,
    settingsRoute,
  ]),
]);

export function makeRouter(queryClient: QueryClient) {
  return createRouter({ routeTree, context: { queryClient }, defaultPreload: "intent" });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}
