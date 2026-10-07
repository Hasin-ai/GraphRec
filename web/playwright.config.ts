import { defineConfig } from "@playwright/test";

// End-to-end suite against the running Compose stack (frontend on FRONTEND_PORT, nginx -> api).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5180",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  outputDir: "e2e-results",
  projects: [{ name: "chromium", use: { browserName: "chromium", viewport: { width: 1440, height: 940 } } }],
});
