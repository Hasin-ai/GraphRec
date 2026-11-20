import { expect, test } from '@playwright/test';

// UC-27 and UC-31 in the console: an administrator locks a member with a reason,
// the member cannot sign in, and the change appears in the tenant's audit trail.
test('administrators lock and unlock members and see it in the audit trail', async ({ page, request }) => {
  test.setTimeout(120_000);
  const tag = Date.now().toString(36);
  const password = `GraphRec-members-${tag}!`;
  const adminEmail = `members-admin-${tag}@example.org`;
  const devEmail = `members-dev-${tag}@example.org`;
  const tenant = await (await request.post('/v1/tenants', { headers: { 'Idempotency-Key': `members-${tag}` }, data: { name: `Members ${tag}`, admin_email: adminEmail } })).json();
  const admin = await (await request.post('/v1/auth/setup-password', { data: { setup_token: tenant.setup_token, password } })).json();
  const invited = await (await request.post('/v1/tenant/users', { headers: { Authorization: `Bearer ${admin.access_token}` }, data: { email: devEmail, role: 'tenant_developer' } })).json();
  expect((await request.post('/v1/auth/setup-password', { data: { setup_token: invited.setup_token, password } })).ok()).toBeTruthy();

  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(adminEmail);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('link', { name: 'Team members', exact: true }).click();
  const row = page.getByRole('row', { name: new RegExp(devEmail) });
  await row.getByRole('button', { name: 'Lock', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Reason (optional)').fill('Left the project');
  await dialog.getByRole('button', { name: 'Lock member' }).click();
  await expect(row).toContainText('Locked');
  expect((await request.post('/v1/auth/login', { data: { email: devEmail, password } })).status()).toBe(401);

  await page.getByRole('link', { name: 'Audit trail', exact: true }).click();
  await expect(page.getByRole('row', { name: /tenant_user_updated/ }).first()).toContainText('Left the project');
});
