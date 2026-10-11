// Usage: node audit/capture.mjs <outDir>   (vite preview must be serving dist on :4999)
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
import { fixture, TENANT_ID, VERSIONS, JOBS } from './fixture.mjs';

const out = process.argv[2] ?? 'audit/before';
mkdirSync(out, { recursive: true });
const tenantRoutes = [
  ['overview', '/home'], ['products', '/products'], ['product-detail', '/products/0'], ['product-new', '/products/new'],
  ['sync', '/products/sync'], ['events', '/events/submit'], ['submission', '/submissions/c8f23e8a-f7bd-4189-abab-806afea09933'],
  ['datasets', '/datasets'], ['training', '/training'], ['training-run', '/training/' + JOBS[0].id],
  ['models', '/models'], ['model-detail', '/models/' + VERSIONS[2].id], ['rules', '/recommendation-rules'],
  ['service-status', '/service-status'], ['usage', '/usage'], ['credentials', '/credentials'], ['integration', '/integration'],
  ['users', '/users'], ['account', '/account'], ['not-found', '/does-not-exist'],
];
const platformRoutes = [['admin-status', '/admin/status'], ['admin-tenants', '/admin/tenants'], ['admin-tenant', '/admin/tenants/' + TENANT_ID], ['admin-plans', '/admin/plans'], ['admin-audit', '/admin/audit']];
const publicRoutes = [['login', '/login'], ['register', '/register'], ['setup', '/setup'], ['recover', '/recover'], ['admin-login', '/admin/login']];
// state variants: [name, route, mode] — mode overrides responses
const states = [
  ['products-empty', '/products', 'empty'], ['models-empty', '/models', 'empty'], ['overview-empty', '/home', 'empty'],
  ['overview-error', '/home', 'error'], ['products-error', '/products', 'error'], ['overview-loading', '/home', 'loading'],
];
const only = process.env.ONLY ? new Set(process.env.ONLY.split(',')) : null;
const configs = (process.env.CONFIGS ?? 'desktop-light,desktop-dark,mobile-light,mobile-dark').split(',');
const viewport = c => c.startsWith('mobile') ? { width: 390, height: 844 } : { width: 1440, height: 900 };

const EMPTY = { '/v1/products': { items: [], total: 0 }, '/v1/model-versions': { items: [] }, '/v1/training-jobs': { items: [] }, '/v1/deployment': { status: 'stopped', active_model_version_id: null, last_transition_at: null, failure_reason: null }, '/v1/usage': { ...fixture['/v1/usage'], dimensions: fixture['/v1/usage'].dimensions.map(d => ({ ...d, used: 0, remaining: d.limit })) }, '/v1/metrics/summary': null };

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const now = Date.now();
async function shoot(name, route, realm, cfg, mode) {
  if (only && !only.has(name)) return;
  const page = await browser.newPage({ viewport: viewport(cfg), deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/v1/**', r => {
    const u = new URL(r.request().url());
    const path = decodeURIComponent(u.pathname);
    if (mode === 'loading') return; // never resolve
    if (mode === 'error' && !path.startsWith('/v1/platform')) return r.fulfill({ status: 503, json: { error: { code: 'service_unavailable', message: 'The service is temporarily unavailable.', correlation_id: '6f1e2a90-1b2c-4d3e-9f00-aa11bb22cc33' } } });
    if (mode === 'empty' && path in EMPTY) return r.fulfill({ json: EMPTY[path] });
    if (r.request().method() !== 'GET') return r.fulfill({ json: {} });
    const body = fixture[path];
    return body === undefined ? r.fulfill({ status: 404, json: { error: { code: 'resource_not_found', message: 'Not found.' } } }) : r.fulfill({ json: body });
  });
  await page.addInitScript(([theme, realm, now]) => {
    localStorage.setItem('graphrec.theme', theme);
    if (realm === 'tenant') sessionStorage.setItem('graphrec.session.tenant', JSON.stringify({ kind: 'tenant', email: 'owner-39f889@beauty.example', role: 'tenant_administrator', scopes: ['catalog:read', 'catalog:write', 'events:write', 'events:read', 'training:read', 'training:write', 'models:read', 'models:write', 'models:deploy', 'deployments:read', 'metrics:read', 'usage:read', 'billing:read', 'keys:write', 'users:write', 'recommendations:read'], accessToken: 'h.' + btoa(JSON.stringify({ tid: 'ef1fb0ef-fd44-4fef-bf92-795c7ccf5134' })) + '.s', expiresAt: now + 3600e3, signedInAt: now - 600e3 }));
    if (realm === 'platform') sessionStorage.setItem('graphrec.session.platform', JSON.stringify({ kind: 'platform', token: 't', signedInAt: now }));
  }, [cfg.endsWith('dark') ? 'dark' : 'light', realm, now]);
  await page.goto('http://localhost:5001' + route);
  await page.waitForTimeout(mode === 'loading' ? 400 : 900);
  await page.screenshot({ path: `${out}/${name}--${cfg}.png`, fullPage: true });
  if (cfg === 'mobile-light' && realm !== 'public') {
    const toggle = page.getByRole('button', { name: /navigation/i }).first();
    if (await toggle.count()) { await toggle.click().catch(() => {}); await page.waitForTimeout(250); await page.screenshot({ path: `${out}/${name}--mobile-nav.png` }); }
  }
  if (errors.length) console.log(name, cfg, 'PAGEERROR', errors.join(' | '));
  await page.close();
}
for (const cfg of configs) {
  for (const [n, r] of publicRoutes) await shoot(n, r, 'public', cfg);
  for (const [n, r] of tenantRoutes) await shoot(n, r, 'tenant', cfg);
  for (const [n, r] of platformRoutes) await shoot(n, r, 'platform', cfg);
  for (const [n, r, m] of states) if (cfg === 'desktop-light' || cfg === 'mobile-light') await shoot(n, r, 'tenant', cfg, m);
}
await browser.close();
console.log('done', out);
