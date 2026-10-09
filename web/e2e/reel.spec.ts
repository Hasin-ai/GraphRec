import { test, expect } from "@playwright/test";

test.describe("Reel Storefront Reference Journey & Capability Proofs", () => {
  const REEL_URL = process.env.REEL_URL ?? "http://localhost:5290";

  test("loads storefront, navigates shelves, inspects status and executes proof battery", async ({ page }) => {
    // 1. Visit Reel storefront homepage
    await page.goto(REEL_URL);
    await expect(page).toHaveTitle(/Reel/);
    await expect(page.locator(".brand")).toContainText("Reel");

    // 2. Verify shelf renders recommended films
    const shelf = page.locator(".shelf").first();
    await expect(shelf).toBeVisible();
    await expect(shelf.locator(".tile")).toHaveCount(10);

    // 3. Open Insight Drawer
    const insightButton = page.locator("button:has-text('How it works')");
    await expect(insightButton).toBeVisible();
    await insightButton.click();

    const drawer = page.locator(".insight");
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText("What GraphRec did");

    // 4. Inspect Status Tab: verify deep readiness and feedback health
    const statusTab = drawer.locator("button[role='tab']:has-text('Status')");
    await statusTab.click();
    await expect(drawer.locator("h4:has-text('Deep Readiness Probes')")).toBeVisible();
    await expect(drawer.locator("h4:has-text('Telemetry Feedback Health')")).toBeVisible();
    await expect(drawer.locator(".readiness-pill")).toHaveCount(4);

    // 5. Inspect Proof Tab & run on-demand capability battery
    const proofTab = drawer.locator("button[role='tab']:has-text('Proof')");
    await proofTab.click();
    await expect(drawer.locator("button:has-text('Run Capability Battery')")).toBeVisible();

    // Trigger run
    await drawer.locator("button:has-text('Run Capability Battery')").click();

    // Verify proof battery completed with 19/19 Verified
    const verifiedBadge = drawer.locator(".proof-badge:has-text('Verified')");
    await expect(verifiedBadge).toBeVisible({ timeout: 20_000 });
    await expect(drawer.locator(".proof-table tbody tr")).toHaveCount(19);

    // 6. Navigate to a film page, watch film, verify event receipt
    await drawer.locator("button.icon[aria-label='Close']").click();
    const firstFilm = page.locator(".shelf .tile").first();
    await firstFilm.click();

    await expect(page.locator(".film-body")).toBeVisible();
    const watchButton = page.locator("button:has-text(\"I've watched this\")");
    await expect(watchButton).toBeVisible();
    await watchButton.click();

    await expect(page.locator(".receipt")).toBeVisible();
    await expect(page.locator(".receipt")).toContainText("Saved to your history");
  });
});
