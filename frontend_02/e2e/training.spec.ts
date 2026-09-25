import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

test('tenant trains a real DGSR model and activates it through the console', async ({ page, request }) => {
  test.setTimeout(180_000);
  const tag = Date.now().toString(36);
  const email = `trained-ui-${tag}@example.org`;
  const password = `Training-${tag}-password!`;
  let registered = await request.post('/v1/tenants', { headers: { 'Idempotency-Key': `training-${tag}` }, data: { name: `Training browser ${tag}`, admin_email: email } });
  if (registered.status() === 429 && registered.headers()['retry-after']) {
    await page.waitForTimeout(Math.min(60, Number(registered.headers()['retry-after'])) * 1000 + 250);
    registered = await request.post('/v1/tenants', { headers: { 'Idempotency-Key': `training-${tag}` }, data: { name: `Training browser ${tag}`, admin_email: email } });
  }
  expect(registered.status()).toBe(201);
  const tenant = await registered.json();
  const auth = await request.post('/v1/auth/setup-password', { data: { setup_token: tenant.setup_token, password } });
  expect(auth.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await auth.json()).access_token}` };
  const products = Array.from({ length: 12 }, (_, i) => ({ external_id: String(i), title: `Training movie ${i}`, category: i % 2 ? 'Drama' : 'Comedy' }));
  expect((await request.post('/v1/products:bulk-upsert', { headers, data: { products } })).ok()).toBeTruthy();
  const events = Array.from({ length: 3 }, (_, u) => Array.from({ length: 8 }, (_, i) => ({
    event_id: `${u}-${i}`, event_type: 'view', user_id: String(u), external_product_id: String((u + i) % 12),
    occurred_at: new Date(Date.UTC(2026, 0, 1, 0, 0, u * 20 + i)).toISOString(),
  }))).flat();
  expect((await request.post('/v1/events/batches', { headers, data: { events } })).ok()).toBeTruthy();
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/home$/);
  await page.goto('/training');
  await page.getByRole('button', { name: 'Start training', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Model source')).toHaveValue('train');
  await dialog.getByLabel('Configuration (optional JSON)').fill('{"epochs":1}');
  await dialog.getByRole('button', { name: 'Request training' }).click();
  await expect(page).toHaveURL(/\/training\/[0-9a-f-]+$/);
  await expect(page.locator('.page-header .tag')).toHaveText('succeeded', { timeout: 60_000 });
  await expect(page.getByText('Development placeholder', { exact: true })).toHaveCount(0);
  await expect(page.getByText('100% · completed', { exact: true })).toBeVisible();
  const folder = resolve('e2e-screens', 'srs');
  mkdirSync(folder, { recursive: true });
  await page.screenshot({ path: resolve(folder, 'real-training-complete.png'), fullPage: true });
  await page.getByRole('button', { name: /^Open model version/ }).click();
  await expect(page.getByText('Development placeholder', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Activate', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: /^Activate / }).click();
  await expect(page.locator('.page-header .tag')).toHaveText('active');
  const rec = await request.post('/v1/recommendations', { headers, data: { user_id: '0', top_n: 2 } });
  expect(rec.ok()).toBeTruthy();
  expect((await rec.json()).strategy).toBe('personalized');
});
