import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setTenantSession } from '../../auth/session';
import { mockFetch, signInAsAdmin, tokenPair } from '../../test/helpers';
import { renderAt } from '../../test/render';

afterEach(() => vi.unstubAllGlobals());
const usage = { period_start: '2026-09-01T00:00:00Z', period_end: '2026-10-01T00:00:00Z', reset_at: '2026-10-01T00:00:00Z', last_reconciled_at: '2026-09-19T00:00:00Z', project_defaults: true,
  dimensions: [{ type: 'training_jobs', used: 0, limit: 0, remaining: 500, unit: 'count' }, { type: 'stored_products', used: 80, limit: 100, remaining: 20, unit: 'count' }, { type: 'training_cpu_seconds', used: 0, limit: null, remaining: null, unit: 'seconds' }] };

describe('operational state', () => {
  it('uses the same zero-limit and warning rules for the usage summary and table', async () => {
    signInAsAdmin();
    mockFetch([{ path: '/v1/usage', body: usage }, { path: '/v1/subscription', body: { plan_code: 'free', status: 'active', limits: {} } }]);
    renderAt('/usage');
    expect(await screen.findByText('1 limit is exhausted')).toBeInTheDocument();
    expect(screen.getByRole('row', { name: /Training jobs/ })).toHaveTextContent('0 remaining');
    expect(screen.getByRole('row', { name: /Training jobs/ })).toHaveTextContent('Exhausted');
    expect(screen.getByRole('row', { name: /Stored products/ })).toHaveTextContent('Approaching limit');
    expect(screen.getByRole('row', { name: /Training cpu seconds/ })).toHaveTextContent('Informational');
  });
  it('blocks training on a zero limit even if the API remaining field is inconsistent', async () => {
    signInAsAdmin();
    mockFetch([{ path: '/v1/usage', body: usage }, { path: '/v1/training-jobs', body: { items: [] } }]);
    renderAt('/training');
    await screen.findByText(/training quota for this period is exhausted/);
    expect(screen.getByRole('button', { name: 'Start training' })).toBeDisabled();
  });
  it('does not offer training while quota verification is pending or failed', async () => {
    signInAsAdmin();
    let finish!: (response: Response) => void;
    vi.stubGlobal('fetch', vi.fn((url: string) => url === '/v1/usage' ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(new Response(JSON.stringify({ items: [] })))));
    renderAt('/training');
    expect(screen.getByRole('button', { name: 'Start training' })).toBeDisabled();
    await act(async () => finish(new Response(JSON.stringify({ error: { message: 'Usage service unavailable' } }), { status: 503 })));
    expect(await screen.findByText('Usage service unavailable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start training' })).toBeDisabled();
    expect(screen.queryByText(/a request would be accepted/)).not.toBeInTheDocument();
  });
  it.each([
    ['/credentials', '/v1/api-keys', 'No credentials yet'],
    ['/products', '/v1/products?limit=50&offset=0', 'No products yet'],
    ['/datasets', '/v1/datasets/snapshots', 'No snapshots yet'],
    ['/models', '/v1/model-versions', 'No model versions yet'],
  ])('does not turn a failed collection read into an empty state at %s', async (route, path, empty) => {
    signInAsAdmin();
    mockFetch([{ path, status: 503, body: { error: { message: 'Read failed' } } }]);
    renderAt(route);
    expect(await screen.findByText('Read failed')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: empty })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
  it('reads only permitted resources on a job detail and shows the actual failure', async () => {
    setTenantSession('reader@example.org', tokenPair({ scopes: ['training:read'] }));
    const { calls } = mockFetch([{ path: '/v1/training-jobs/job-1', body: { id: 'job-1', status: 'failed', configuration: { pretrained_artifact: 'checkpoint' }, model_version_id: 'model-1', failure_reason: 'Checkpoint has no compatible catalog items', created_at: '2026-09-18T00:00:00Z' } }]);
    renderAt('/training/job-1');
    expect(await screen.findByText('Checkpoint has no compatible catalog items')).toBeInTheDocument();
    expect(calls.some(call => call.url.includes('/v1/training-jobs/job-1'))).toBe(true);
    expect(calls.some(call => call.url.includes('model-versions'))).toBe(false);
    expect(screen.queryByRole('button', { name: 'Cancel job' })).not.toBeInTheDocument();
  });
  it('does not claim model activation until the API confirms it', async () => {
    signInAsAdmin();
    const user = userEvent.setup();
    let active = false;
    let finish!: (response: Response) => void;
    const version = { id: 'model-1', version_tag: 'version-one', model_type: 'dgsr', status: 'eligible', metrics: {}, created_at: '2026-09-18T00:00:00Z' };
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => init?.method === 'POST' ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(new Response(JSON.stringify({ items: [{ ...version, status: active ? 'active' : 'eligible' }] })))));
    renderAt('/models');
    const activate = await screen.findByRole('button', { name: 'Activate' });
    await user.click(activate);
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Activate version-one' }));
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.queryByText('version-one activated.')).not.toBeInTheDocument();
    active = true;
    await act(async () => finish(new Response(JSON.stringify({ ...version, status: 'active' }))));
    expect(await screen.findByText('version-one activated.')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(await screen.findByText('active', { selector: '.tag' })).toBeInTheDocument();
  });
  it('clears catalog filters together without restoring either URL value', async () => {
    signInAsAdmin();
    const user = userEvent.setup();
    mockFetch([{ path: '/v1/products?limit=50&offset=0', body: { total: 1, items: [{ id: 'p-1', external_id: 'SKU-1', title: 'Brass hinge', availability_status: 'available', is_active: true, price: '5' }] } }]);
    renderAt('/products?q=oak&availability=unavailable');
    await screen.findByText('No products match on this page');
    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(await screen.findByRole('link', { name: 'Brass hinge' })).toBeInTheDocument();
    expect(screen.getByLabelText('Search this page')).toHaveValue('');
    expect(screen.getByLabelText('Availability on this page')).toHaveValue('all availability');
  });
  it('paginates the catalog through the API and hides the previous page on failure', async () => {
    signInAsAdmin();
    const user = userEvent.setup();
    const { calls } = mockFetch([
      { path: '/v1/products?limit=50&offset=0', body: { total: 100, items: [{ id: 'p-1', external_id: 'SKU-1', title: 'First-page product', availability_status: 'available', is_active: true, price: '5' }] } },
      { path: '/v1/products?limit=50&offset=50', status: 503, body: { error: { message: 'Second page unavailable' } } },
    ]);
    renderAt('/products');
    await screen.findByText('First-page product');
    await user.click(screen.getByRole('button', { name: 'Next' }));
    await screen.findByText('Second page unavailable');
    expect(screen.queryByText('First-page product')).not.toBeInTheDocument();
    expect(calls.some(call => call.url.endsWith('offset=50'))).toBe(true);
  });
  it('shows the rate-limit store as degraded on Service Status when Redis is down (D16)', async () => {
    signInAsAdmin();
    mockFetch([{ path: '/v1/deployment', body: { status: 'stopped', active_model_version_id: null, last_transition_at: null, failure_reason: null,
      rate_limiter: { backend: 'redis', status: 'degraded', fail_open_total: 7, last_error_at: '2026-10-01T17:00:00Z' } } }]);
    renderAt('/service-status');
    expect(await screen.findByText('Rate-limit store unavailable')).toBeInTheDocument();
    expect(screen.getByText('redis · degraded')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
  });
});
