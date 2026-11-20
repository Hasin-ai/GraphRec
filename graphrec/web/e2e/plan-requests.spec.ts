import { expect, test, type Browser, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

/**
 * No payments: a tenant administrator requests Free demo, Basic or Pro and a platform
 * operator approves (activating the plan) or rejects it. Two real browser sessions
 * against the live stack.
 */
test.describe.configure({ mode: "serial" });

const tag = `pr${Date.now().toString(36)}`;
const tenantName = `Plan Request ${tag}`;
const adminEmail = `plan-${tag}@example.org`;
const password = "correct-horse-battery-staple";
const operatorEmail = `plan-operator-${tag}@example.org`;
const operatorPassword = `Operator-${tag}-password`;

let tenant: Page;
let operator: Page;

function platformToken(): string {
  const env = readFileSync(resolve(here, "..", "..", ".env"), "utf8");
  const line = env.split(/\r?\n/).find((l) => l.startsWith("PLATFORM_ADMIN_TOKEN="));
  return line?.slice("PLATFORM_ADMIN_TOKEN=".length).trim() ?? "";
}

test.beforeAll(async ({ browser }: { browser: Browser }) => {
  tenant = await (await browser.newContext()).newPage();
  operator = await (await browser.newContext()).newPage();
});
test.afterAll(async () => { await tenant.context().close(); await operator.context().close(); });

async function decide(decision: "Approve" | "Reject", reason: string) {
  await operator.goto("/admin/plan-requests");
  const row = operator.getByRole("row", { name: new RegExp(tenantName) });
  await expect(row).toContainText("pending");
  await row.getByRole("button", { name: decision }).click();
  const dialog = operator.getByRole("dialog");
  await dialog.getByLabel("Reason").fill(reason);
  await dialog.getByRole("button", { name: decision === "Approve" ? /^Approve and activate/ : "Reject request" }).click();
  await expect(dialog).toBeHidden();
}

test("a tenant requests Basic from the pricing page and waits for approval", async () => {
  await tenant.goto("/register");
  await tenant.getByLabel("Business name").fill(tenantName);
  await tenant.getByLabel("Work email").fill(adminEmail);
  await tenant.getByLabel("Password", { exact: true }).fill(password);
  await tenant.getByLabel("Confirm password").fill(password);
  await tenant.getByRole("button", { name: "Create account" }).click();
  await expect(tenant.getByRole("heading", { name: "Overview" })).toBeVisible();

  await tenant.goto("/pricing");
  await tenant.getByRole("link", { name: "Request Basic" }).click();
  const dialog = tenant.getByRole("dialog", { name: "Request a different plan" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("radio", { name: /^Basic/ })).toBeChecked();
  await expect(dialog.getByRole("radio", { name: /^Free/ })).toHaveCount(0);   // the current plan is not offered
  await dialog.getByLabel("Note for the operator (optional)").fill("Launching next week");
  await dialog.getByRole("button", { name: "Request Basic" }).click();
  await expect(tenant.getByText("Basic plan requested — waiting for approval")).toBeVisible();
  await expect(tenant.locator(".plan-title")).toContainText("Free plan");
  await expect(tenant.getByRole("button", { name: "Change plan" })).toHaveCount(0);
});

test("the operator sees it on Platform Status and approves it; the tenant is on Basic", async () => {
  const created = await operator.request.post("/v1/platform/operators", {
    headers: { Authorization: `Bearer ${platformToken()}`, Accept: "application/json" },
    data: { email: operatorEmail, display_name: "Plan Approver", password: operatorPassword, roles: ["plan_management", "monitoring"] },
  });
  expect(created.status()).toBe(201);
  await operator.goto("/admin/login");
  await operator.getByLabel("Operator email").fill(operatorEmail);
  await operator.getByLabel("Password", { exact: true }).fill(operatorPassword);
  await operator.getByRole("button", { name: "Sign in" }).click();
  await expect(operator.getByRole("heading", { name: "Platform Status" })).toBeVisible();
  await expect(operator.getByText(/plan requests? awaiting approval/)).toBeVisible();
  await operator.getByRole("link", { name: "Review requests" }).click();
  await expect(operator.getByRole("heading", { name: "Plan requests" })).toBeVisible();
  await expect(operator.getByRole("row", { name: new RegExp(tenantName) })).toContainText("Launching next week");

  await decide("Approve", "Approved for the launch");
  await expect(operator.getByText(/is now on Basic/)).toBeVisible();
  await operator.getByRole("tab", { name: "Approved" }).click();
  await expect(operator.getByRole("row", { name: new RegExp(tenantName) })).toContainText("Approved for the launch");

  await tenant.goto("/usage");
  await expect(tenant.locator(".plan-title")).toContainText("Basic plan");
  await expect(tenant.getByText("Basic plan approved")).toBeVisible();
  await expect(tenant.getByText(/Approved for the launch/)).toBeVisible();
});

test("a rejected request keeps the plan and shows the reason; a pending one can be cancelled", async () => {
  await tenant.getByRole("button", { name: "Change plan" }).click();
  const dialog = tenant.getByRole("dialog", { name: "Request a different plan" });
  await dialog.getByRole("radio", { name: /^Pro/ }).check();
  await dialog.getByRole("button", { name: "Request Pro" }).click();
  await expect(tenant.getByText("Pro plan requested — waiting for approval")).toBeVisible();

  await decide("Reject", "Start with Basic for a month");
  await tenant.reload();
  await expect(tenant.locator(".plan-title")).toContainText("Basic plan");
  await expect(tenant.getByText("Pro plan request was not approved")).toBeVisible();
  await expect(tenant.getByText(/Start with Basic for a month/)).toBeVisible();

  // Every tier can be requested, including going back to Free demo - and withdrawn.
  await tenant.getByRole("button", { name: "Change plan" }).click();
  await tenant.getByRole("dialog").getByRole("radio", { name: /^Free/ }).check();
  await expect(tenant.getByRole("dialog")).toContainText("Moving to a smaller plan lowers your limits");
  await tenant.getByRole("dialog").getByRole("button", { name: /^Request Free/ }).click();
  await expect(tenant.getByText(/Free demo plan requested — waiting for approval/)).toBeVisible();
  await tenant.getByRole("button", { name: "Cancel request" }).click();
  await expect(tenant.getByText("Plan request cancelled.")).toBeVisible();
  await expect(tenant.getByRole("button", { name: "Change plan" })).toBeVisible();
});
