/**
 * Acceptance flow (M8): login -> create project -> add layers -> add attributes -> publish, then
 * the bundle of the UI-created project matches what seed_pilot produced (same layer keys, schemas
 * and resolved capture profiles).
 */
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8000";
const USER = "manager@pilot.local";
const PASSWORD = "pilot-pass-2026";
const run = Date.now().toString(36);

const here = dirname(fileURLToPath(import.meta.url));
const examples = join(here, "..", "..", "..", "packages", "schema", "examples");
const farmers = JSON.parse(readFileSync(join(examples, "farmers.layer-schema.json"), "utf8"));
const farms = JSON.parse(readFileSync(join(examples, "farms.layer-schema.json"), "utf8"));
const farmProfile = JSON.parse(readFileSync(join(examples, "farms.capture-profile.json"), "utf8"));

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email or phone number").fill(USER);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Projects" })).toBeVisible();
}

async function apiToken(request: APIRequestContext): Promise<{ token: string; orgId: string }> {
  const r = await request.post(`${API}/api/v1/auth/login`, {
    data: { identifier: USER, password: PASSWORD },
  });
  const token = (await r.json()).access_token as string;
  const me = await (
    await request.get(`${API}/api/v1/me`, { headers: { Authorization: `Bearer ${token}` } })
  ).json();
  return { token, orgId: me.memberships[0].org_id as string };
}

test("login, create the pilot project and layers in the UI, publish, and match the seed bundle", async ({
  page,
  request,
}) => {
  await login(page);

  // --- create project
  await page.getByRole("button", { name: "New project" }).click();
  await page.getByLabel("Name").fill(`UI Pilot ${run}`);
  await page.getByLabel("Description").fill("Created through the web app");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name: `UI Pilot ${run}` })).toBeVisible();

  // --- project-level capture rule (what seed_pilot sets: stream every 3 m)
  await page.getByRole("button", { name: "Import JSON" }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Capture profile JSON")
    .fill(JSON.stringify({ stream: { intervalMeters: 3 } }));
  await page.getByRole("dialog").getByRole("button", { name: "Import" }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Project capture rules saved")).toBeVisible();

  // --- add Farmers (no geometry) and Farms (polygon)
  for (const [name, key, geometry] of [
    ["Farmers", "lyr_farmers", "No geometry (table)"],
    ["Farms", "lyr_farms", "Polygon"],
  ] as const) {
    await page.getByRole("button", { name: "Add layer" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Name").fill(name);
    await dialog.getByLabel("Key").fill(key);
    await dialog.getByLabel("Geometry").selectOption({ label: geometry });
    await dialog.getByRole("button", { name: "Create" }).click();
    await expect(page.getByRole("link", { name })).toBeVisible();
  }

  // --- Farmers attributes: add one by hand in the builder, then import the pilot schema and publish
  await page.getByRole("link", { name: "Farmers" }).click();
  await page.getByLabel("Add attribute of type").selectOption("text");
  await expect(page.getByRole("list", { name: "Attributes" }).getByRole("listitem")).toHaveCount(1);
  await importSchema(page, farmers);
  await expect(
    page.getByRole("list", { name: "Attributes" }).getByText("full_name", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Draft saved")).toBeVisible();
  await page.getByRole("tab", { name: "Publish" }).click();
  await expect(page.getByText("No problems found")).toBeVisible();
  await page.getByRole("button", { name: /Publish version 1/ }).click();
  await expect(page.getByText(/Published version 1/)).toBeVisible();

  // --- Farms: import schema (relation -> lyr_farmers), capture rules, publish
  await page.getByRole("link", { name: "← Project" }).click();
  await page.getByRole("link", { name: "Farms" }).click();
  await importSchema(page, farms);
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("Draft saved")).toBeVisible();
  await page.getByRole("tab", { name: "Capture rules" }).click();
  await importProfile(page, farmProfile);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Capture rules saved")).toBeVisible();
  await page.getByRole("tab", { name: "Publish" }).click();
  await expect(page.getByText("No problems found")).toBeVisible();
  await page.getByRole("button", { name: /Publish version 1/ }).click();
  await expect(page.getByText(/Published version 1/)).toBeVisible();

  // --- compare bundles: UI project vs seed_pilot project
  const { token, orgId } = await apiToken(request);
  const headers = { Authorization: `Bearer ${token}`, "X-Org-Id": orgId };
  const projects = await (await request.get(`${API}/api/v1/projects`, { headers })).json();
  const seeded = projects.find((p: { name: string }) => p.name === "Western North Farm Mapping");
  const mine = projects.find((p: { name: string }) => p.name === `UI Pilot ${run}`);
  expect(seeded && mine).toBeTruthy();
  const bundle = async (id: string) =>
    (await request.get(`${API}/api/v1/projects/${id}/bundle`, { headers })).json();
  const a = await bundle(seeded.id);
  const b = await bundle(mine.id);
  const normalise = (bundleBody: { layers: Array<Record<string, unknown>> }) =>
    bundleBody.layers.map((l) => ({
      key: l.key,
      geometry_type: l.geometry_type,
      schema_version: l.schema_version,
      fields: (l.schema as { fields: unknown }).fields,
      lists: l.lists,
      capture_profile: l.capture_profile,
    }));
  expect(normalise(b)).toEqual(normalise(a));
});

async function importSchema(page: Page, schema: unknown) {
  await page.getByRole("button", { name: "Import JSON" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Schema JSON").fill(JSON.stringify(schema));
  await dialog.getByRole("button", { name: "Import" }).click();
}

async function importProfile(page: Page, profile: unknown) {
  await page.getByRole("button", { name: "Import JSON" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Capture profile JSON").fill(JSON.stringify(profile));
  await dialog.getByRole("button", { name: "Import" }).click();
}
