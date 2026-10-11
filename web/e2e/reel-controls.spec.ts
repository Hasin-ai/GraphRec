import { test, expect, type Page } from "@playwright/test";

// Reel storefront demo controls: the guest reset and the diversity slider.
const REEL_URL = process.env.REEL_URL ?? "http://localhost:5290";

const shelfTitles = async (page: Page) =>
  (await page.locator(".shelf").first().locator(".tile-title").allTextContents()).join(" | ");

test("a guest can start over with a fresh session and no history", async ({ page }) => {
  await page.goto(REEL_URL);
  await expect(page.getByText("Popular right now")).toBeVisible();
  const reset = page.getByRole("button", { name: "Reset guest" });
  await expect(reset).toBeDisabled();

  await page.locator(".shelf .tile").first().click();
  await page.getByRole("button", { name: "I've watched this" }).click();
  await expect(page.getByText("In your history")).toBeVisible();
  await page.getByRole("banner").getByRole("link", { name: "Home", exact: true }).click();
  await expect(page.locator(".tile-reason").first()).toBeVisible({ timeout: 30_000 });
  await expect(reset).toBeEnabled();

  const before = (await (await page.request.get(`${REEL_URL}/api/reel/session`)).json()).data.sessionId;
  await reset.click();
  await expect(page.getByText("Started over as a new guest")).toBeVisible();
  await expect(page.getByText("Popular right now")).toBeVisible();
  const after = (await (await page.request.get(`${REEL_URL}/api/reel/session`)).json()).data;
  expect(after.sessionId).not.toBe(before);
  expect(after.persona.key).toBe("anon");
  expect((await (await page.request.get(`${REEL_URL}/api/reel/insight/history`)).json()).data).toEqual([]);
  await expect(reset).toBeDisabled();
});

test("the diversity slider re-ranks once per change and is deterministic", async ({ page }) => {
  const sent: (number | undefined)[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/api/reel/recommendations")) sent.push(r.postDataJSON().diversity);
  });
  await page.goto(REEL_URL);
  await page.evaluate(() => { try { localStorage.removeItem("reel.diversity"); } catch { /* ignore */ } });
  const select = page.locator("select").first();
  const options = await select.locator("option").allTextContents();
  await select.selectOption({ index: options.findIndex((o) => o.startsWith("Theo")) });
  await expect(page.getByText("Recommended for you")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Reset guest" })).toBeHidden();
  const base = await shelfTitles(page);

  const slider = page.getByRole("slider", { name: "Diversity" });
  await expect(slider).toHaveAttribute("max", "0.8");
  sent.length = 0;
  await slider.focus();
  for (let i = 0; i < 8; i++) await page.keyboard.press("ArrowRight");
  await expect(page.locator(".diversity b")).toHaveText("0.65");
  await expect.poll(() => sent).toEqual([0.65]);
  await expect.poll(() => shelfTitles(page)).not.toBe(base);

  sent.length = 0;
  await page.locator(".diversity .link").click();
  await expect.poll(() => sent).toEqual([0.25]);
  await expect.poll(() => shelfTitles(page)).toBe(base);
});
