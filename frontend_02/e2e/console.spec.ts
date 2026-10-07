import { expect, test, type Browser, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

/**
 * Full journey against the live stack: register -> setup -> credentials ->
 * catalog -> events -> datasets -> training -> models -> serving -> usage ->
 * sign out / sign in -> platform realm -> gates. Every step is a real request
 * through nginx to the API and Postgres; nothing is mocked.
 */
test.describe.configure({ mode: "serial" });

// One page for the whole journey: the login and API-key endpoints are rate-limited per
// account (8/min and 10/min), so the suite signs in once and carries the session through.
let page: Page;
test.beforeAll(async ({ browser }: { browser: Browser }) => {
  page = await browser.newPage();
});
test.afterAll(async () => {
  await page.close();
});

const tag = Date.now().toString(36);
const tenantName = `E2E Tenant ${tag}`;
const adminEmail = `e2e-${tag}@example.org`;
const password = "correct-horse-battery-staple";
const shots = resolve(here, "..", "e2e-screens");
let shotIndex = 0;
let setupLink = "";
let versionTag = "";
// The usable storefront credential, carried to the serving-metrics story.
let probeSecret = "";

function platformToken(): string {
  const env = readFileSync(resolve(here, "..", "..", ".env"), "utf8");
  const line = env.split(/\r?\n/).find((l) => l.startsWith("PLATFORM_ADMIN_TOKEN="));
  const value = line?.slice("PLATFORM_ADMIN_TOKEN=".length).trim() ?? "";
  if (!value) throw new Error("PLATFORM_ADMIN_TOKEN is empty in .env; the platform realm is disabled");
  return value;
}

async function shot(page: Page, name: string) {
  shotIndex += 1;
  await page.screenshot({ path: resolve(shots, `${String(shotIndex).padStart(2, "0")}-${name}.png`), fullPage: true, mask: [page.locator('[data-testid="secret-value"], [data-testid="setup-link"], input[type="password"]')] });
}

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(adminEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Sign-in returns to the page that required it (or Home), so assert the tenant shell instead.
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
}

test("public: the landing page leads to registration, which creates a tenant with a one-time setup link", async () => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1, name: "Recommendations that learn from every interaction." })).toBeVisible();
  await shot(page, "landing");

  await page.getByRole("main").getByRole("link", { name: "Create a tenant" }).first().click();
  await expect(page).toHaveURL(/\/register$/);
  await page.getByLabel("Business name").fill(tenantName);
  await page.getByLabel("Administrator email").fill(adminEmail);
  await shot(page, "register");
  await page.getByRole("button", { name: "Create tenant" }).click();

  await expect(page.getByRole("heading", { name: "Tenant created" })).toBeVisible();
  setupLink = (await page.getByTestId("setup-link").textContent()) ?? "";
  expect(setupLink).toMatch(/\/setup#token=/);
  await expect(page.getByText(adminEmail)).toBeVisible();
  await shot(page, "register-created");

  // "Open setup now" carries the administrator email into the setup form.
  await page.getByRole("link", { name: "Open setup now" }).click();
  await expect(page.getByLabel("Email (optional cross-check)")).toHaveValue(adminEmail);
  await expect(page.getByLabel("Setup token")).not.toHaveValue("");

  // Registering the same business + administrator email again (new idempotency key) is a conflict, form still filled.
  await page.goto("/register");
  await page.getByLabel("Business name").fill(tenantName);
  await page.getByLabel("Administrator email").fill(adminEmail);
  await page.getByRole("button", { name: "Create tenant" }).click();
  await expect(page.getByText("This registration already exists")).toBeVisible();
  await expect(page.getByLabel("Business name")).toHaveValue(tenantName);
  await shot(page, "register-conflict");
});

test("setup: the token activates the administrator and signs them in", async () => {
  await page.goto(setupLink);
  await expect(page.getByLabel("Setup token")).not.toHaveValue("");
  // The one-time token is scrubbed from the URL once read.
  await expect(page).toHaveURL(/\/setup$/);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm").fill(password);
  await shot(page, "setup");
  await page.getByRole("button", { name: "Activate account" }).click();

  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Administrator", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: `Workspace: ${tenantName}` })).toBeVisible();
  await expect(page.getByText("Add your catalog", { exact: true })).toBeVisible();
  await expect(page.getByText("0 of 4 steps done")).toBeVisible();
  await shot(page, "home-fresh");

  // A used token is rejected without disclosure.
  await page.goto("/login");
  await page.evaluate(() => window.sessionStorage.clear());
  await page.goto(setupLink);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm").fill(password);
  await page.getByRole("button", { name: "Activate account" }).click();
  await expect(page.getByText("This link cannot be used")).toBeVisible();
  await shot(page, "setup-reused");
});

test("sign-in: wrong password is non-disclosing, right password lands on Home", async () => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(adminEmail);
  await page.getByLabel("Password").fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Sign-in failed")).toBeVisible();
  await shot(page, "login-failed");
  await signIn(page);
});

test("credentials: create shows the secret once; rotate and revoke enforce state", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "API Credentials" }).click();
  await expect(page.getByRole("heading", { name: "No credentials yet" })).toBeVisible();
  await shot(page, "credentials-empty");

  await page.getByRole("button", { name: "Create credential" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Credential name").fill("Storefront server");
  await dialog.getByLabel(/Recommendation requests/).check();
  await shot(page, "credentials-create-dialog");
  await dialog.getByRole("button", { name: "Create credential" }).click();

  const secret = page.getByTestId("secret-value");
  await expect(secret).toBeVisible();
  const secretText = (await secret.textContent()) ?? "";
  expect(secretText).toMatch(/^gr_live_/);
  await shot(page, "credentials-secret");
  await page.getByRole("button", { name: "I have stored it" }).click();
  await expect(secret).toBeHidden();

  const row = page.getByRole("row", { name: /Storefront server/ });
  await expect(row).toContainText("2 permissions");
  await expect(row).toContainText("active");

  // The issued secret authenticates as an ApiKey through the same proxy.
  const status = await page.evaluate(async (s) => (await fetch("/v1/products", { headers: { Accept: "application/json", Authorization: `ApiKey ${s}` } })).status, secretText);
  expect(status).toBe(200);

  await row.getByRole("button", { name: "Rotate" }).click();
  await page.getByRole("dialog").getByLabel("Reason").fill("Scheduled rotation");
  await page.getByRole("dialog").getByRole("button", { name: "Rotate credential" }).click();
  await expect(page.getByTestId("secret-value")).toBeVisible();
  await page.getByRole("button", { name: "I have stored it" }).click();

  await row.getByRole("button", { name: "Revoke" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Revoke" }).click();
  await expect(row).toContainText("revoked");
  await expect(row.getByRole("button", { name: "Rotate" })).toBeDisabled();
  await shot(page, "credentials-revoked");

  // Create one that stays usable for the integration page and, later, for real serving traffic.
  await page.getByRole("button", { name: "Create credential" }).first().click();
  await page.getByRole("dialog").getByLabel("Credential name").fill("Event pipeline");
  await page.getByRole("dialog").getByLabel(/Recommendation requests/).check();
  await page.getByRole("dialog").getByRole("button", { name: "Create credential" }).click();
  probeSecret = (await page.getByTestId("secret-value").textContent()) ?? "";
  expect(probeSecret).toMatch(/^gr_live_/);
  await page.getByRole("button", { name: "I have stored it" }).click();

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Integration" }).click();
  await expect(page.getByText("1 usable")).toBeVisible();
  await shot(page, "integration");
});

test("catalog: synchronize, list, filter, detail, update and disable", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Catalog sync" }).click();
  const collection = {
    products: [
      { external_id: "SKU-4471", title: "Brass hinge, 75mm", category: "Hardware", price: "8.40", metadata: { brand: "Northgate" } },
      { external_id: "SKU-5120", title: "Oak shelf board 1200", category: "Timber", price: "22.00", availability_status: "available" },
      { external_id: "SKU-6002", title: "Cordless driver 18V", category: "Power tools", price: "129.00" },
      { external_id: "SKU-BAD", title: "Negative", price: "-1" },
    ],
  };
  // A schema-invalid item rejects the whole collection with the offending field named.
  await page.getByLabel("Product collection (JSON)").fill(JSON.stringify(collection, null, 2));
  await page.getByRole("button", { name: "Submit synchronization" }).click();
  await expect(page.getByText("The collection cannot be accepted")).toBeVisible();
  await expect(page.getByText(/products\.3\.price/)).toBeVisible();
  await shot(page, "catalog-sync-rejected");

  collection.products.pop();
  await page.getByLabel("Product collection (JSON)").fill(JSON.stringify(collection, null, 2));
  await page.getByRole("button", { name: "Submit synchronization" }).click();
  await expect(page.getByRole("heading", { name: "Synchronization applied" })).toBeVisible();
  await expect(page.getByText("No item was rejected.")).toBeVisible();
  await shot(page, "catalog-sync-result");

  await page.getByRole("link", { name: "Open products" }).click();
  await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
  await expect(page.getByRole("row", { name: /SKU-4471/ })).toContainText("Available");
  await page.getByLabel("Search this page").fill("Oak");
  await expect(page.getByRole("row", { name: /SKU-5120/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /SKU-4471/ })).toBeHidden();
  await page.getByRole("button", { name: "Clear" }).click();
  await shot(page, "products");

  await page.getByRole("link", { name: "Brass hinge, 75mm" }).click();
  await expect(page.getByRole("heading", { name: "Brass hinge, 75mm" })).toBeVisible();
  await page.getByLabel("Title").fill("Brass hinge, 75 mm (solid)");
  await page.getByRole("button", { name: "Update product" }).click();
  await expect(page.getByRole("heading", { name: "Brass hinge, 75 mm (solid)" })).toBeVisible();
  await shot(page, "product-detail");

  await page.getByRole("button", { name: "Disable product" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Disable product" }).click();
  await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
  await expect(page.getByRole("row", { name: /SKU-4471/ })).toContainText("Not recommended");

  // Add product: duplicate identifier is accepted as an idempotent update, not an error.
  await page.getByRole("button", { name: "Add product" }).click();
  await page.getByLabel("External product id").fill("SKU-7311");
  await page.getByLabel("Title").fill("Leather work gloves");
  await page.getByLabel("Price").fill("14.20");
  await page.getByRole("button", { name: "Save product" }).click();
  await expect(page.getByRole("heading", { name: "Leather work gloves" })).toBeVisible();
});

test("events: single accept, duplicate confirmation, batch and submission detail", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Events" }).click();
  await page.getByLabel("Event identifier").fill(`ev-${tag}-1`);
  await page.getByLabel("Customer identifier", { exact: true }).fill("cus-1");
  await page.getByLabel("External product id").fill("SKU-6002");
  await page.getByLabel("Event type").selectOption("purchase");
  await page.getByRole("button", { name: "Submit event" }).click();
  await expect(page.getByRole("heading", { name: "Event accepted" })).toBeVisible();
  await shot(page, "event-accepted");

  await page.getByRole("button", { name: "Submit another" }).click();
  await page.getByLabel("Event identifier").fill(`ev-${tag}-1`);
  await page.getByRole("button", { name: "Submit event" }).click();
  await expect(page.getByRole("heading", { name: "Duplicate confirmed" })).toBeVisible();
  await shot(page, "event-duplicate");

  await page.getByRole("button", { name: "Submit another" }).click();
  await page.getByLabel("Submission mode").selectOption("batch");
  const batch = { events: Array.from({ length: 6 }, (_, i) => ({ event_id: `ev-${tag}-b${i % 5}`, event_type: i % 2 ? "view" : "add_to_cart", user_id: `cus-${i}`, external_product_id: i % 2 ? "SKU-5120" : "SKU-6002" })) };
  await page.getByLabel("Event collection (JSON)").fill(JSON.stringify(batch));
  await page.getByRole("button", { name: "Submit batch" }).click();
  await expect(page.getByRole("heading", { name: "Batch accepted" })).toBeVisible();
  await expect(page.getByText("completed")).toBeVisible();
  await shot(page, "batch-accepted");

  await page.getByRole("button", { name: "Open submission result" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /^Event batch/ })).toBeVisible();
  // The batch is applied in the submitting request: the console shows its final counts, not a pipeline.
  await expect(page.getByText("these are its final counts", { exact: false })).toBeVisible();
  await expect(page.locator(".stat").filter({ hasText: /^Received/ })).toContainText("6");
  await shot(page, "submission");
});

test("datasets: take a snapshot and see it listed", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Datasets" }).click();
  await expect(page.getByRole("heading", { name: "No snapshots yet" })).toBeVisible();
  await page.getByRole("button", { name: "Take snapshot" }).first().click();
  await page.getByRole("dialog").getByRole("button", { name: "Create snapshot" }).click();
  await expect(page.getByRole("heading", { name: "Dataset snapshots" })).toBeVisible();
  await expect(page.getByText("1 snapshots")).toBeVisible();
  await page.getByText("Import products and events from a file", { exact: true }).click();
  await page.getByLabel("Dataset file").setInputFiles({ name: 'audit.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify({ products: [{ external_id: 'UPLOAD-1', title: 'Uploaded product', price: '4.00' }], events: [{ event_id: `upload-${tag}`, event_type: 'view', user_id: 'upload-user', external_product_id: 'UPLOAD-1' }] })) });
  await page.getByRole('button', { name: 'Upload dataset' }).click();
  await expect(page.getByText('2 snapshots')).toBeVisible();
  await expect(page.locator('.stat').filter({ hasText: /^Accepted products/ })).toContainText('1');
  await shot(page, "datasets");
});

test("training and models: request a job, activate the version, see it serving", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Training" }).click();
  await expect(page.getByRole("button", { name: "Start training" }).first()).toBeEnabled();
  await shot(page, "training-empty");

  await page.getByRole("button", { name: "Start training" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Model source").selectOption("placeholder");
  await dialog.getByLabel("Dataset snapshot").selectOption({ index: 1 });
  await dialog.getByRole("button", { name: "Request training" }).click();

  await expect(page.getByRole("heading", { level: 1, name: /training run$/ })).toBeVisible();
  await expect(page.getByText("The job completed and registered a model version", { exact: false })).toBeVisible();
  // A placeholder run is never presented as trained on tenant data.
  await expect(page.getByText("Synthetic placeholder (development only)")).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel job" })).toHaveCount(0);
  await expect(page.getByText("Development placeholder", { exact: true }).first()).toBeVisible();
  await shot(page, "training-job");

  await page.getByRole("button", { name: /^Open model version/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: / model · v\d+$/ })).toBeVisible();
  versionTag = (await page.getByRole("heading", { level: 1 }).textContent()) ?? "";
  await expect(page.getByText("No offline metrics were recorded", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Activate" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Roll back" })).toHaveCount(0);
  await shot(page, "model-version");

  await page.getByRole("button", { name: "Activate" }).click();
  await page.getByRole("dialog").getByRole("button", { name: /^Activate / }).click();
  await expect(page.getByText("Selected for recommendation requests.", { exact: false }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Archive" })).toHaveCount(0);
  await shot(page, "model-version-active");

  // The registry and overview reflect the confirmed active model.
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Model Versions" }).click();
  await expect(page.getByText("v1 serving")).toBeVisible();

  // Quota: the free plan allows one training job per period, so the console blocks a second request.
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Training" }).click();
  await expect(page.getByRole("button", { name: "Start training" })).toBeDisabled();
  await expect(page.getByText("quota for this period is exhausted", { exact: false }).first()).toBeAttached();
  await shot(page, "training-blocked");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Model Versions" }).click();
  await expect(page.getByText("v1 serving")).toBeVisible();
  await shot(page, "models");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Service Status" }).click();
  await expect(page.getByRole("heading", { name: "Service Status" })).toBeVisible();
  await expect(page.getByText("available").first()).toBeVisible();
  await expect(page.getByText(versionTag).first()).toBeVisible();
  // This tenant has served no recommendation requests, so every measured rate reads
  // "Not available" rather than a nominal zero, and the window is stated as empty.
  await expect(page.getByText("No requests in this window", { exact: true })).toBeVisible();
  // Unavailable measurements read "—", never a nominal zero.
  await expect(page.locator(".stat").filter({ hasText: /^p95 latency/ }).locator(".value")).toHaveText("—");
  await expect(page.locator(".stat").filter({ hasText: /^Error rate/ }).locator(".value")).toHaveText("—");
  await expect(page.locator(".stat").filter({ hasText: /^Fallback rate/ }).locator(".value")).toHaveText("—");
  await expect(page.getByText("Serving capacity is logical", { exact: false })).toBeVisible();
  await shot(page, "service-status");
});

test("service status: serving traffic is measured and reported", async () => {
  // Serving has no console screen, so drive it the way an integration does: the
  // credential issued earlier, sending real requests through the same proxy this page reads from.
  const served = await page.evaluate(async (s) => {
    const codes: number[] = [];
    for (let i = 0; i < 3; i += 1) {
      const response = await fetch("/v1/recommendations", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `ApiKey ${s}` },
        body: JSON.stringify({ user_id: `cus-${i}`, top_n: 5 }),
      });
      codes.push(response.status);
    }
    return codes;
  }, probeSecret);
  expect(served).toEqual([200, 200, 200]);

  // The board is already open from the previous test and still shows what it read
  // then: nothing here polls, so the readings only change when they are re-read.
  await expect(page.locator(".stat").filter({ hasText: /^Requests/ })).toContainText("0");
  await page.getByRole("button", { name: "Refresh" }).click();
  // The same three requests, now counted and timed by the API's own ledger.
  await expect(page.locator(".stat").filter({ hasText: /^Requests/ })).toContainText("3");
  await expect(page.locator(".stat").filter({ hasText: /^p95 latency/ })).toContainText("ms");
  await expect(page.locator(".stat").filter({ hasText: /^Error rate/ })).toContainText("0%");
  await expect(page.getByText("No requests in this window", { exact: true })).toBeHidden();
  await shot(page, "service-status-measured");
});

test("usage, account and overview reflect the work done", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Usage & Quotas" }).click();
  await expect(page.getByText("9 usage types")).toBeVisible();
  const trainingUsage = page.getByRole("row", { name: /^Training jobs / });
  await expect(trainingUsage).toContainText("At limit");
  await expect(trainingUsage).toContainText("1 of 1");
  await expect(page.locator("summary").filter({ hasText: "Subscription" })).toBeVisible();
  await shot(page, "usage");

  await page.getByRole("button", { name: /^Account menu for / }).click();
  await page.getByRole("menuitem", { name: "Account" }).click();
  await expect(page.getByRole("heading", { name: "What you can do" })).toBeVisible();
  await shot(page, "account");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("heading", { name: "Serving model" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recommendation traffic" })).toBeVisible();
  await shot(page, "home-complete");
});

test("gates: expired session, unknown resource, and sign out", async () => {
  await page.goto("/models/00000000-0000-4000-8000-000000000000");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();
  await shot(page, "not-found");

  await page.goto("/nowhere");
  await expect(page.getByRole("heading", { name: "Not found" })).toBeVisible();

  // A token the API rejects ends the session and routes to sign-in.
  await page.evaluate(() => {
    const raw = window.sessionStorage.getItem("graphrec.session.tenant");
    if (raw) window.sessionStorage.setItem("graphrec.session.tenant", JSON.stringify({ ...JSON.parse(raw), accessToken: "not.a.token" }));
  });
  await page.goto("/credentials");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  // Signing in returns to the page that required the session.
  await signIn(page);
  await expect(page.getByRole("heading", { name: "API Credentials" })).toBeVisible();
  await (await page.getByRole("button", { name: /^Account menu for / }).click(), page.getByRole("menuitem", { name: "Sign out" }).click());
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/home");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("platform realm: token sign-in, tenant detail, quota override, suspension and audit", async () => {
  await page.goto("/admin/tenants");
  await expect(page.getByRole("heading", { name: "Platform sign-in" })).toBeVisible();
  await page.getByLabel("Platform administrator token").fill("wrong-token");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Sign-in failed")).toBeVisible();

  await page.getByLabel("Platform administrator token").fill(platformToken());
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Tenants" })).toBeVisible();
  await shot(page, "platform-tenants");

  await page.getByLabel("Search").fill(tenantName);
  const row = page.getByRole("row", { name: new RegExp(tenantName) });
  await expect(row).toContainText("active");
  await row.getByRole("button", { name: "Open" }).click();
  await expect(page.getByRole("heading", { name: tenantName })).toBeVisible();

  await page.getByRole("button", { name: "Approve quota override" }).click();
  await page.getByRole("dialog").getByLabel("Usage type").selectOption("accepted_events");
  await page.getByRole("dialog").getByLabel("Override limit").fill("8000000");
  await page.getByRole("dialog").getByLabel("Reason (optional)").fill("Launch campaign allowance");
  await page.getByRole("dialog").getByRole("button", { name: "Approve override" }).click();
  await expect(page.getByRole("row", { name: /^Accepted events/ }).first()).toContainText("8,000,000");
  await page.getByRole('button', { name: 'Assign plan', exact: true }).click();
  await page.getByRole('dialog').getByLabel('Plan', { exact: true }).selectOption({ label: 'Pro' });
  await page.getByRole('dialog').getByRole('button', { name: 'Assign plan', exact: true }).click();
  await expect(page.getByText('Current: pro', { exact: true })).toBeVisible();
  await expect(page.getByRole('row', { name: /^Accepted events/ }).first()).toContainText('8,000,000');
  await shot(page, "platform-tenant");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Platform Status" }).click();
  await expect(page.getByText("healthy").first()).toBeVisible();
  await shot(page, "platform-status");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Plans & Quotas" }).click();
  await page.getByRole("link", { name: "free" }).click();
  await expect(page.getByText("Training jobs", { exact: true }).first()).toBeVisible();
  await shot(page, "platform-plan");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Failures & Audit" }).click();
  await page.getByRole("tab", { name: "Audit records" }).click();
  await expect(page.getByRole("row", { name: /quota.overrides_changed/ }).first()).toBeVisible();
  await shot(page, "platform-audit");

  // Suspend the tenant: its sessions stop verifying immediately.
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Tenants" }).click();
  await page.getByLabel("Search").fill(tenantName);
  await page.getByRole("row", { name: new RegExp(tenantName) }).getByRole("button", { name: "Change status" }).click();
  await page.getByRole("dialog").getByLabel("New status").selectOption("suspended");
  // UC-27: the change is refused until a reason is given, and the reason is audited.
  await expect(page.getByRole("dialog").getByRole("button", { name: "Apply status change" })).toBeDisabled();
  await page.getByRole("dialog").getByLabel("Reason").fill("E2E suspension check");
  await page.getByRole("dialog").getByRole("button", { name: "Apply status change" }).click();
  await expect(page.getByRole("row", { name: new RegExp(tenantName) })).toContainText("suspended");
  await shot(page, "platform-suspended");

  await (await page.getByRole("button", { name: /^Account menu for / }).click(), page.getByRole("menuitem", { name: "Sign out" }).click());
  await page.goto("/login");
  await page.getByLabel("Email").fill(adminEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Sign-in failed")).toBeVisible();
});
