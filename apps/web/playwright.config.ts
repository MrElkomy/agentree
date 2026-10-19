import { defineConfig, devices } from "@playwright/test";

// The web origin must match the backend's AGENTREE_ALLOWED_ORIGINS (CSRF Origin check).
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
// Local-only escape hatch when the preinstalled Chromium doesn't match this Playwright version.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], launchOptions: { executablePath } },
    },
  ],
  // Reuses a server that is already running (CI starts `npm run start` itself).
  webServer: {
    command: "npm run start",
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
