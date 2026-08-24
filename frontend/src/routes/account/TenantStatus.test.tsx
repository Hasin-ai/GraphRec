import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { TenantStatusRoute } from './TenantStatus';
import { StateGateLayout } from '../../layouts/StateGateLayout';
import { tenantStatusGuard } from '../../guards';
import { renderRoutes } from '../../test/harness';
import { resetSessionsForTest, store } from '../../api/session';

const SESSION = {
  access_token: 'access-1',
  expires_at: '2026-01-01T00:15:00Z',
  refresh_token: 'refresh-1',
  refresh_expires_at: '2026-01-08T00:00:00Z',
};

const SUSPENDED = {
  tenant_id: '11111111-1111-1111-1111-111111111111',
  tenant_code: 'acme',
  tenant_name: 'Acme Ltd',
  status: 'suspended',
  plan_code: 'standard',
  status_reason: 'Unpaid invoice 4471.',
  created_at: '2026-01-01T00:00:00Z',
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function render() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderRoutes(
    [
      {
        element: <StateGateLayout />,
        children: [
          {
            path: '/account/tenant-status',
            loader: ({ request }) => tenantStatusGuard(queryClient, request),
            element: <TenantStatusRoute />,
          },
        ],
      },
      { path: '/home', element: <h1>Home</h1> },
    ],
    ['/account/tenant-status'],
  );
}

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
  vi.stubGlobal('fetch', vi.fn());
  store('tenant', SESSION);
});

describe('/account/tenant-status', () => {
  it('reads the one endpoint gate 2 exempts, and only that one', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, SUSPENDED));
    render();

    expect(await screen.findByRole('heading', { name: 'Acme Ltd' })).toBeVisible();
    expect(vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url))).toEqual([
      '/v1/tenant',
    ]);
  });

  it('states the lifecycle position and what the platform said about it', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, SUSPENDED));
    render();

    expect(await screen.findByText('suspended')).toBeVisible();
    expect(screen.getByText(/Unpaid invoice 4471\./)).toBeVisible();
    expect(screen.getByText(/Platform Administrator/)).toBeVisible();
  });

  it('suppresses navigation, leaving only the way out', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, SUSPENDED));
    render();
    await screen.findByRole('heading', { name: 'Acme Ltd' });

    // §6: navigation suppressed. Every destination is behind the gate that sent
    // the reader here, so a sidebar would be a list of links back to this page.
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeVisible();
  });

  it('offers no action on the tenant itself, because there is none to offer', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, SUSPENDED));
    render();
    await screen.findByRole('heading', { name: 'Acme Ltd' });

    const labels = screen.getAllByRole('button').map((button) => button.textContent ?? '');
    expect(labels.join(' ').toLowerCase()).not.toMatch(/activate|reinstate|appeal|request/);
  });

  it('does not strand a reader whose tenant has since been activated', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, { ...SUSPENDED, status: 'active' }));
    render();
    expect(await screen.findByRole('heading', { name: 'Home' })).toBeVisible();
  });
});
