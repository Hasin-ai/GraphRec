import { expect, test } from '@playwright/test';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Real API data in a fresh, explicitly named test tenant. No production mocks.
test('all routes render in both themes and at responsive widths', async ({ page, request }) => {
  test.setTimeout(360_000);
  const phase = process.env.AUDIT_PHASE ?? 'after';
  const folder = resolve('e2e-screens', phase);
  mkdirSync(folder, { recursive: true });
  const tag = Date.now().toString(36);
  const email = `frontend-audit-${tag}@example.org`;
  const password = `Audit-only-${tag}-password`;
  const api = async (path: string, data?: unknown, token?: string, method = data ? 'POST' : 'GET') => {
    const options = {
      method, data, headers: { Accept: 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(path === '/tenants' ? { 'Idempotency-Key': tag } : {}) },
    };
    let response = await request.fetch(`/v1${path}`, options);
    if (response.status() === 429 && response.headers()['retry-after']) {
      await new Promise(resolve => setTimeout(resolve, Math.min(60, Number(response.headers()['retry-after'])) * 1000 + 250));
      response = await request.fetch(`/v1${path}`, options);
    }
    expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
    return response.json();
  };
  const registration = await api('/tenants', { name: `Frontend audit ${tag}`, admin_email: email });
  const auth = await api('/auth/setup-password', { setup_token: registration.setup_token, password, email });
  const token = auth.access_token;
  await api('/products/AUDIT-1', { external_id: 'AUDIT-1', title: 'Audit product', price: '24.00', category: 'Test catalog' }, token, 'PUT');
  const batch = await api('/events/batches', { events: [{ event_id: `audit-${tag}`, event_type: 'purchase', user_id: 'audit-user', external_product_id: 'AUDIT-1' }] }, token);
  const snapshot = await api('/datasets/snapshots', {}, token);
  const job = await api('/training-jobs', { dataset_snapshot_id: snapshot.id, configuration: { mode: 'placeholder' } }, token);
  await api(`/model-versions/${job.model_version_id}:activate`, {}, token);

  const failures: string[] = [];
  const report: object[] = [];
  page.on('pageerror', error => failures.push(error.message));
  const capture = async (route: string, label: string, width = 1440) => {
    await page.setViewportSize({ width, height: 940 });
    await page.goto(route);
    await expect(page.locator('h1')).toBeVisible();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('.skeleton')).toHaveCount(0);
    // The real credentials endpoint allows 10 reads/minute. Do not certify a
    // throttled screenshot as the page's normal data state during this sweep.
    const limited = page.getByText(/Too many requests\. Try again in/).first();
    if (await limited.isVisible()) {
      const seconds = Number((await limited.innerText()).match(/in (\d+) seconds/)?.[1] ?? 30);
      await page.waitForTimeout(Math.min(seconds + 1, 60) * 1000);
      await page.reload();
      await page.waitForLoadState('networkidle');
      await expect(limited).toBeHidden();
    }
    await page.screenshot({ path: resolve(folder, `${label}-${width}.png`), fullPage: true, animations: 'disabled', mask: [page.locator('[data-testid="secret-value"], [data-testid="setup-link"], input[type="password"]')] });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    report.push({ route, width, title: await page.locator('h1').innerText(), overflow });
    if (phase !== 'before') expect(overflow, `${route} at ${width}px overflows`).toBe(false);
  };
  for (const route of ['/', '/pricing', '/login', '/register', '/setup', '/invite/accept', '/recover', '/recover/confirm', '/admin/login', '/403', '/404', '/error', '/missing']) {
    await capture(route, `public-${route.replaceAll('/', '-')}`);
    await capture(route, `public-${route.replaceAll('/', '-')}`, 390);
  }
  // The public marketing pages at every sweep width, signed out (signed in, `/` redirects to the console).
  for (const width of [1024, 768, 320]) {
    for (const route of ['/', '/pricing']) await capture(route, `responsive-public-${route === '/' ? 'landing' : route.slice(1)}`, width);
  }
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/home$/);
  const tenantRoutes = ['/home', '/account', '/integration', '/credentials', '/products', '/products/new', '/products/sync', '/products/AUDIT-1', '/events/submit', `/submissions/${batch.id}`, '/datasets', '/training', `/training/${job.id}`, '/models', `/models/${job.model_version_id}`, '/usage', '/service-status'];
  for (const [i, route] of tenantRoutes.entries()) {
    await capture(route, `tenant-${String(i).padStart(2, '0')}`);
    await capture(route, `tenant-${String(i).padStart(2, '0')}`, 390);
  }
  for (const width of [1024, 768, 320]) {
    for (const route of ['/home', '/products', '/usage', '/datasets', '/credentials', '/training', '/integration']) await capture(route, `responsive-${route.slice(1)}`, width);
  }
  await page.setViewportSize({ width: 1440, height: 940 });
  // Theme lives in the account menu: Light, Dark, System.
  await page.getByRole('button', { name: /^Account menu for / }).click();
  await page.getByRole('menuitemradio', { name: 'Dark' }).click();
  await page.keyboard.press('Escape');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await capture('/usage', 'dark-usage');
  await capture('/products', 'dark-products', 390);
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await expect(page.getByRole('button', { name: 'Close navigation' }).and(page.locator('[aria-expanded]'))).toHaveAttribute('aria-expanded', 'true');
  await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: 'API Credentials' }).click();
  await expect(page.getByRole('button', { name: 'Open navigation' })).toHaveAttribute('aria-expanded', 'false');
  await page.getByRole('button', { name: 'Create credential', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const bounds = await dialog.boundingBox();
  expect(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 390).toBeTruthy();
  await page.screenshot({ path: resolve(folder, 'mobile-credential-dialog.png'), fullPage: true, animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();

  const env = readFileSync(resolve('..', '.env'), 'utf8');
  const admin = env.split(/\r?\n/).find(line => line.startsWith('PLATFORM_ADMIN_TOKEN='))?.slice(21).trim();
  if (admin) {
    await page.setViewportSize({ width: 1440, height: 940 });
    await page.goto('/admin/login');
    await page.getByRole('button', { name: 'Use the development bootstrap token instead' }).click();
    await page.getByLabel('Bootstrap token').fill(admin);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page).toHaveURL(/\/admin\/status$/);
    const plans = await api('/platform/plans', undefined, admin);
    const platformRoutes = ['/admin/status', '/admin/tenants', `/admin/tenants/${registration.id}`, '/admin/plans', `/admin/plans/${plans[0].id}`, '/admin/audit', '/admin/operators'];
    for (const [i, route] of platformRoutes.entries()) {
      await capture(route, `platform-${i}`);
      await capture(route, `platform-${i}`, 390);
    }
    await page.setViewportSize({ width: 1440, height: 940 });
    // Theme lives in the account menu: Light, Dark, System.
  await page.getByRole('button', { name: /^Account menu for / }).click();
  await page.getByRole('menuitemradio', { name: 'Dark' }).click();
  await page.keyboard.press('Escape');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    for (const [i, route] of platformRoutes.entries()) await capture(route, `platform-light-${i}`);
  }
  writeFileSync(resolve(folder, 'routes.json'), JSON.stringify({ report, failures }, null, 2));
  expect(failures).toEqual([]);
});

