import { defineConfig } from "@playwright/test";

// End-to-end suite against a running ReelStore instance (default: http://localhost:5290).
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.REEL_URL ?? "http://localhost:5290",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  outputDir: "e2e-results",
  projects: [{ name: "chromium", use: { browserName: "chromium", viewport: { width: 1440, height: 940 } } }],
});
