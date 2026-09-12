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

function platformToken(): string {
  const env = readFileSync(resolve(here, "..", "..", ".env"), "utf8");
  const line = env.split(/\r?\n/).find((l) => l.startsWith("PLATFORM_ADMIN_TOKEN="));
  const value = line?.slice("PLATFORM_ADMIN_TOKEN=".length).trim() ?? "";
  if (!value) throw new Error("PLATFORM_ADMIN_TOKEN is empty in .env; the platform realm is disabled");
  return value;
}

async function shot(page: Page, name: string) {
  shotIndex += 1;
  await page.screenshot({ path: resolve(shots, `${String(shotIndex).padStart(2, "0")}-${name}.png`), fullPage: true });
}

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(adminEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Sign-in returns to the page that required it (or Home), so assert the tenant shell instead.
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
}

test("public: root redirects to sign-in and registration creates a tenant with a one-time setup link", async () => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await shot(page, "login");

  await page.goto("/register");
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

  await expect(page.getByRole("heading", { name: "Home" })).toBeVisible();
  await expect(page.getByText("tenant administrator").first()).toBeVisible();
  await expect(page.getByText("Getting to first recommendations")).toBeVisible();
  await expect(page.getByText("0 usable")).toBeVisible();
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
  await expect(row).toContainText("2 operations");
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

  // Create one that stays usable for the integration page.
  await page.getByRole("button", { name: "Create credential" }).first().click();
  await page.getByRole("dialog").getByLabel("Credential name").fill("Event pipeline");
  await page.getByRole("dialog").getByRole("button", { name: "Create credential" }).click();
  await page.getByRole("button", { name: "I have stored it" }).click();

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Integration" }).click();
  await expect(page.getByText("1 usable")).toBeVisible();
  await shot(page, "integration");
});

test("catalog: synchronize, list, filter, detail, update and disable", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Synchronize Catalog" }).click();
  const collection = {
    products: [
      { external_id: "SKU-4471", title: "Brass hinge, 75mm", category: "Hardware", price: "8.40", metadata: { brand: "Northgate" } },
      { external_id: "SKU-5120", title: "Oak shelf board 1200", category: "Timber", price: "22.00", availability_status: "low_stock" },
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
  await expect(page.getByRole("row", { name: /SKU-4471/ })).toContainText("served");
  await page.getByLabel("Category").selectOption("Timber");
  await expect(page.getByRole("row", { name: /SKU-5120/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /SKU-4471/ })).toBeHidden();
  await page.getByRole("button", { name: "Clear" }).click();
  await shot(page, "products");

  await page.getByRole("link", { name: "SKU-4471" }).click();
  await expect(page.getByRole("heading", { name: "Brass hinge, 75mm" })).toBeVisible();
  await page.getByLabel("Title").fill("Brass hinge, 75 mm (solid)");
  await page.getByRole("button", { name: "Update product" }).click();
  await expect(page.getByRole("heading", { name: "Brass hinge, 75 mm (solid)" })).toBeVisible();
  await shot(page, "product-detail");

  await page.getByRole("button", { name: "Disable product" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Disable product" }).click();
  await expect(page.getByRole("heading", { name: "Products" })).toBeVisible();
  await expect(page.getByRole("row", { name: /SKU-4471/ })).toContainText("ineligible");

  // Add product: duplicate identifier is accepted as an idempotent update, not an error.
  await page.getByRole("button", { name: "Add product" }).click();
  await page.getByLabel("External product id").fill("SKU-7311");
  await page.getByLabel("Title").fill("Leather work gloves");
  await page.getByLabel("Price").fill("14.20");
  await page.getByRole("button", { name: "Save product" }).click();
  await expect(page.getByRole("heading", { name: "Leather work gloves" })).toBeVisible();
});

test("events: single accept, duplicate confirmation, batch and submission detail", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Submit Events" }).click();
  await page.getByLabel("Event identifier").fill(`ev-${tag}-1`);
  await page.getByLabel("Customer identifier").fill("cus-1");
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
  await expect(page.getByRole("heading", { name: /^Submission / })).toBeVisible();
  await expect(page.getByText("All items handled.")).toBeVisible();
  await shot(page, "submission");
});

test("datasets: take a snapshot and see it listed", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Datasets" }).click();
  await expect(page.getByRole("heading", { name: "No snapshots yet" })).toBeVisible();
  await page.getByRole("button", { name: "Take snapshot" }).first().click();
  await page.getByRole("dialog").getByLabel("Description (optional)").fill("e2e snapshot");
  await page.getByRole("dialog").getByRole("button", { name: "Create snapshot" }).click();
  await expect(page.getByRole("heading", { name: "Dataset snapshots" })).toBeVisible();
  await expect(page.getByText("1 snapshots")).toBeVisible();
  await shot(page, "datasets");
});

test("training and models: request a job, activate the version, see it serving", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Training" }).click();
  await expect(page.getByText("eligible", { exact: true })).toBeVisible();
  await shot(page, "training-empty");

  await page.getByRole("button", { name: "Start training" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Dataset snapshot").selectOption({ index: 1 });
  await dialog.getByRole("button", { name: "Request training" }).click();

  await expect(page.getByRole("heading", { name: /^[0-9a-f]{8}/ })).toBeVisible();
  await expect(page.getByText("The job completed and registered a model version", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel job" })).toBeDisabled();
  await shot(page, "training-job");

  await page.getByRole("button", { name: /^Open model version / }).click();
  await expect(page.getByRole("heading", { name: /^v\d{14}-/ })).toBeVisible();
  versionTag = (await page.getByRole("heading", { level: 1 }).textContent()) ?? "";
  await expect(page.getByText("No offline metrics were recorded", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Activate" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Roll back" })).toBeDisabled();
  await shot(page, "model-version");

  await page.getByRole("button", { name: "Activate" }).click();
  await page.getByRole("dialog").getByRole("button", { name: /^Activate / }).click();
  await expect(page.getByText("This version is serving traffic now.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Archive" })).toBeDisabled();
  await shot(page, "model-version-active");

  // The sidebar service rail reflects the activation on the next navigation.
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Model Versions" }).click();
  await expect(page.locator(".aside-badges")).toContainText(versionTag);
  await expect(page.locator(".aside-badges")).toContainText("available");

  // Quota: the free plan allows one training job per period, so the console blocks a second request.
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Training" }).click();
  await expect(page.getByRole("button", { name: "Start training" })).toBeDisabled();
  await expect(page.getByText("quota for this period is exhausted", { exact: false }).first()).toBeVisible();
  await shot(page, "training-blocked");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Model Versions" }).click();
  await expect(page.getByRole("row", { name: new RegExp(versionTag) })).toContainText("serving");
  await shot(page, "models");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Service Status" }).click();
  await expect(page.getByRole("heading", { name: "Service Status" })).toBeVisible();
  await expect(page.getByText("available").first()).toBeVisible();
  await expect(page.getByText(versionTag).first()).toBeVisible();
  await shot(page, "service-status");
});

test("usage, account and home checklist reflect the work done", async () => {
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Usage & Quotas" }).click();
  await expect(page.getByText("9 of 9")).toBeVisible();
  await expect(page.getByRole("row", { name: /^training_jobs 1 1 0/ })).toContainText("exhausted");
  await expect(page.getByRole("heading", { name: "Subscription" })).toBeVisible();
  await shot(page, "usage");

  await page.getByRole("link", { name: "Account" }).click();
  await expect(page.getByRole("heading", { name: "Capabilities of this session" })).toBeVisible();
  await shot(page, "account");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Home" }).click();
  await expect(page.getByText(/\d of 7 complete/)).toHaveText("7 of 7 complete");
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
  await page.getByRole("button", { name: "Sign out" }).click();
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
  await page.getByRole("dialog").getByRole("button", { name: "Approve override" }).click();
  await expect(page.getByRole("row", { name: /accepted_events/ })).toContainText("8,000,000");
  await shot(page, "platform-tenant");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Platform Status" }).click();
  await expect(page.getByText("healthy").first()).toBeVisible();
  await shot(page, "platform-status");

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Plans & Quotas" }).click();
  await page.getByRole("link", { name: "free" }).click();
  await expect(page.getByText("training_jobs", { exact: true })).toBeVisible();
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
  await page.getByRole("dialog").getByLabel("Reason").fill("End of e2e run");
  await page.getByRole("dialog").getByRole("button", { name: "Apply status change" }).click();
  await expect(page.getByRole("row", { name: new RegExp(tenantName) })).toContainText("suspended");
  await shot(page, "platform-suspended");

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.goto("/login");
  await page.getByLabel("Email").fill(adminEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Sign-in failed")).toBeVisible();
});
