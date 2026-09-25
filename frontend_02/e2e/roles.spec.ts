import { expect, test } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

test('new administrators and developers have working role-scoped consoles and isolated tenants', async ({ page, browser, request }) => {
  test.setTimeout(120_000);
  const tag = Date.now().toString(36);
  const password = `GraphRec-demo-${tag}!`;
  const adminEmail = `srs-admin-${tag}@example.org`;
  const developerEmail = `srs-dev-${tag}@example.org`;
  const secondAdminEmail = `srs-manager-${tag}@example.org`;
  const register = async (name: string, email: string) => {
    const response = await request.post('/v1/tenants', { headers: { 'Idempotency-Key': `${tag}-${name}` }, data: { name: `SRS ${name} ${tag}`, admin_email: email } });
    expect(response.status()).toBe(201);
    const tenant = await response.json();
    const setup = await request.post('/v1/auth/setup-password', { data: { setup_token: tenant.setup_token, password } });
    expect(setup.ok()).toBeTruthy();
    return { tenant, token: (await setup.json()).access_token };
  };
  const a = await register('Cinema A', adminEmail);
  const b = await register('Cinema B', `srs-other-${tag}@example.org`);
  const authA = { Authorization: `Bearer ${a.token}` };
  const authB = { Authorization: `Bearer ${b.token}` };
  const productA = await request.put('/v1/products/SHARED-MOVIE', { headers: authA, data: { external_id: 'SHARED-MOVIE', title: 'Cinema A movie', price: '4' } });
  expect(productA.ok()).toBeTruthy();
  const productB = await request.put('/v1/products/SHARED-MOVIE', { headers: authB, data: { external_id: 'SHARED-MOVIE', title: 'Cinema B movie', price: '8' } });
  expect(productB.ok()).toBeTruthy();
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(adminEmail);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await page.getByRole('link', { name: 'Team members', exact: true }).click();
  await expect(page.getByRole('row', { name: new RegExp(adminEmail) })).toContainText('Active');
  const invitations: Record<string, string> = {};
  for (const [email, role] of [[developerEmail, 'tenant_developer'], [secondAdminEmail, 'tenant_administrator']]) {
    await page.getByRole('button', { name: 'Invite member', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Email', { exact: true }).fill(email);
    await dialog.getByLabel('Role', { exact: true }).selectOption(role);
    await dialog.getByRole('button', { name: 'Create invitation' }).click();
    await expect(page.getByText('Save this invitation link', { exact: true })).toBeVisible();
    invitations[email] = (await page.getByTestId('setup-link').textContent())!;
    await page.getByRole('button', { name: 'I have saved the invitation' }).click();
  }
  const results: object[] = [];
  for (const [email, role] of [[developerEmail, 'tenant_developer'], [secondAdminEmail, 'tenant_administrator']]) {
    const context = await browser.newContext();
    const member = await context.newPage();
    await member.goto(invitations[email]);
    await member.getByLabel('Password', { exact: true }).fill(password);
    await member.getByLabel('Confirm').fill(password);
    await member.getByRole('button', { name: 'Activate account' }).click();
    await expect(member).toHaveURL(/\/home$/);
    const session = await member.evaluate(() => JSON.parse(sessionStorage.getItem('graphrec.session.tenant')!));
    expect(session.role).toBe(role);
    const headers = { Authorization: `Bearer ${session.accessToken}` };
    await member.goto('/products/SHARED-MOVIE');
    await expect(member.getByRole('heading', { name: 'Cinema A movie' })).toBeVisible();
    await expect(member.getByText('Cinema B movie')).toHaveCount(0);
    if (role === 'tenant_developer') {
      await member.getByLabel('Title', { exact: true }).fill('Cinema A edited by developer');
      await member.getByRole('button', { name: 'Update product', exact: true }).click();
      await expect(member.getByRole('heading', { name: 'Cinema A edited by developer' })).toBeVisible();
      for (const route of ['/users', '/models', '/usage', '/service-status']) {
        await member.goto(route);
        await expect(member).toHaveURL(/\/403$/);
      }
      expect((await request.get('/v1/tenant/users', { headers })).status()).toBe(403);
      expect((await request.post('/v1/training-jobs', { headers, data: {} })).status()).toBe(403);
      expect((await request.post('/v1/api-keys', { headers, data: { name: 'Escalation attempt', scopes: ['models:deploy'] } })).status()).toBe(403);
      await member.goto('/credentials');
      await member.getByRole('button', { name: 'Create credential', exact: true }).first().click();
      await expect(member.getByRole('checkbox')).toHaveCount(5);
      await member.getByLabel('Credential name').fill('SRS developer store');
      await member.getByRole('checkbox', { name: 'Recommendation requests' }).check();
      await member.getByRole('dialog').getByRole('button', { name: 'Create credential', exact: true }).click();
      const secret = (await member.getByTestId('secret-value').textContent())!;
      const scoped = { Authorization: `ApiKey ${secret}` };
      expect((await request.get('/v1/products/SHARED-MOVIE', { headers: scoped })).ok()).toBeTruthy();
      expect((await request.post('/v1/training-jobs', { headers: scoped, data: {} })).status()).toBe(403);
      expect((await request.get('/v1/tenant/users', { headers: scoped })).status()).toBe(401);
      await member.getByRole('button', { name: 'I have stored it' }).click();
    } else {
      await member.goto('/users');
      await expect(member.getByRole('row', { name: new RegExp(developerEmail) })).toContainText('Active');
    }
    results.push({ role, email, result: 'passed' });
    await context.close();
    // Restore the fixture title for the next actor; Tenant B remains unchanged.
    await request.put('/v1/products/SHARED-MOVIE', { headers: authA, data: { external_id: 'SHARED-MOVIE', title: 'Cinema A movie', price: '4' } });
  }
  expect((await (await request.get('/v1/products/SHARED-MOVIE', { headers: authB })).json()).title).toBe('Cinema B movie');
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByText('3 members')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 940 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  mkdirSync(resolve('e2e-screens/srs'), { recursive: true });
  await page.screenshot({ path: resolve('e2e-screens/srs/team-members-mobile.png'), fullPage: true });
  writeFileSync(resolve('e2e-screens/srs/role-results.json'), JSON.stringify({ tenant: a.tenant.id, results, crossTenant: 'passed' }, null, 2));
});
