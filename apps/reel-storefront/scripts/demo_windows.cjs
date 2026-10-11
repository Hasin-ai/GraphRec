// Opens one Chrome window per role for a live GraphRec + Reel demo (local test accounts only).
//   npm i playwright-core   (in any folder), then: node demo_windows.cjs
// Credentials are read from apps/reel-storefront/.env (written by bootstrap_reel.py); nothing is printed.
const fs = require("fs"), path = require("path"), os = require("os");
const { chromium } = require("playwright-core");
const ENV = Object.fromEntries(fs.readFileSync(path.join(__dirname, "..", ".env"), "utf8").split(/\r?\n/)
  .filter((l) => l.includes("=") && !l.startsWith("#")).map((l) => [l.slice(0, l.indexOf("=")).trim(), l.slice(l.indexOf("=") + 1).trim()]));
const CONSOLE = process.env.CONSOLE_URL || "http://localhost:5180";
const REEL = process.env.REEL_URL || "http://localhost:5290";
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

async function signIn(page, email, password, landing) {
  await page.goto(`${CONSOLE}/login`);
  await page.fill("#email", email);
  await page.fill("#password", password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 20000 });
  await page.goto(`${CONSOLE}${landing}`);
}

(async () => {
  const ctx = await chromium.launchPersistentContext(path.join(os.tmpdir(), "graphrec-demo-profile"), {
    headless: false, executablePath: CHROME, viewport: null, args: ["--new-window"],
  });
  const first = ctx.pages()[0] || (await ctx.newPage());
  const status = {};
  // 1. Tenant administrator: model versions (active imported DGSR checkpoint)
  try { await signIn(first, ENV.REEL_ADMIN_EMAIL, ENV.REEL_ADMIN_PASSWORD, "/models"); status.admin = "signed in"; }
  catch (e) { status.admin = "FAILED " + e.message.split("\n")[0]; }
  // 2. Tenant developer: integration page (API keys, catalogue, events)
  const dev = await ctx.newPage();
  try { await signIn(dev, ENV.REEL_DEVELOPER_EMAIL, ENV.REEL_DEVELOPER_PASSWORD, "/integration"); status.developer = "signed in"; }
  catch (e) { status.developer = "FAILED " + e.message.split("\n")[0]; }
  // 3. Platform administrator: separate realm; the operator enters PLATFORM_ADMIN_TOKEN by hand
  const platform = await ctx.newPage();
  await platform.goto(`${CONSOLE}/admin/login`); status.platform = "login page open (enter token)";
  // 4. Shopper: Reel storefront as Maya (real MovieLens user 184387)
  const shop = await ctx.newPage();
  await shop.goto(REEL);
  await shop.evaluate(() => fetch("/api/reel/session/persona", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona: "maya" }) }));
  await shop.reload(); status.shopper = "Reel as Maya";
  for (const [p, t] of [[first, "Tenant admin"], [dev, "Developer"], [platform, "Platform admin"], [shop, "Shopper"]])
    await p.evaluate((t) => { document.title = `[${t}] ` + document.title; }, t).catch(() => {});
  console.log(JSON.stringify(status));
  await new Promise(() => {}); // keep the windows open
})();
