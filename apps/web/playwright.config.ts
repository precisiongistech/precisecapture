import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run the Vite dev server (proxying /api to the API on :8000) against an API
 * that has `seed_pilot` data. Locally: `make dev-up api-migrate`, `manage.py seed_pilot`,
 * `make api-run`, then `pnpm --filter web e2e`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "line" : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: "pnpm exec vite --port 5173 --strictPort",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
