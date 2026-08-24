import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient } from '@tanstack/react-query';
import { TENANT_ROOT_ID, TenantLayout } from './TenantLayout';
import { HomeRoute } from '../routes/Home';
import { RouteErrorBoundary } from '../routes/errors/RouteErrorBoundary';
import { tenantGuard } from '../guards';
import { renderRoutes } from '../test/harness';
import { hasSession, resetSessionsForTest, store } from '../api/session';

const SESSION = {
  access_token: 'access-1',
  expires_at: '2026-01-01T00:15:00Z',
  refresh_token: 'refresh-1',
  refresh_expires_at: '2026-01-08T00:00:00Z',
};

const TENANT = {
  tenant_id: '11111111-1111-1111-1111-111111111111',
  tenant_code: 'acme',
  tenant_name: 'Acme Ltd',
  status: 'active',
  plan_code: 'standard',
  status_reason: null,
  created_at: '2026-01-01T00:00:00Z',
};

function me(role: 'tenant_administrator' | 'tenant_developer') {
  return {
    tenant_user_id: '22222222-2222-2222-2222-222222222222',
    tenant_id: TENANT.tenant_id,
    email: role === 'tenant_administrator' ? 'admin@acme.test' : 'dev@acme.test',
    display_name: 'Someone',
    role,
    status: 'active',
  };
}

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
        id: TENANT_ROOT_ID,
        element: <TenantLayout />,
        loader: ({ request }) => tenantGuard(queryClient, request),
        errorElement: <RouteErrorBoundary />,
        children: [{ path: '/home', element: <HomeRoute /> }],
      },
      { path: '/login', element: <h1>Sign in</h1> },
      { path: '/account/tenant-status', element: <h1>Tenant status</h1> },
    ],
    ['/home'],
  );
}

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
  vi.stubGlobal('fetch', vi.fn());
});

describe('the tenant shell', () => {
  it('refuses to render at all without a session', async () => {
    render();
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeVisible();
    // Gate 1 decided before a single tenant-scoped query went out.
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('sends a suspended tenant to the status page instead of the shell', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, { ...TENANT, status: 'suspended' }));

    render();
    expect(await screen.findByRole('heading', { name: /tenant status/i })).toBeVisible();
  });

  it('shows an Administrator the administrative modules', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(json(200, TENANT))
      .mockResolvedValueOnce(json(200, me('tenant_administrator')));

    render();
    await screen.findByRole('heading', { name: 'Acme Ltd' });

    const nav = screen.getByRole('navigation', { name: /primary/i });
    expect(nav).toHaveTextContent('Training');
    expect(nav).toHaveTextContent('Users');
    expect(nav).not.toHaveTextContent('Products');
  });

  it('shows a Developer the catalogue and none of the administration', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(json(200, TENANT))
      .mockResolvedValueOnce(json(200, me('tenant_developer')));

    render();
    await screen.findByRole('heading', { name: 'Acme Ltd' });

    const nav = screen.getByRole('navigation', { name: /primary/i });
    expect(nav).toHaveTextContent('Products');
    expect(nav).not.toHaveTextContent('Training');
    expect(nav).not.toHaveTextContent('Users');
  });

  it('carries no tenant switcher — the tenant comes from the session', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(json(200, TENANT))
      .mockResolvedValueOnce(json(200, me('tenant_administrator')));

    render();
    await screen.findByRole('heading', { name: 'Acme Ltd' });
    expect(screen.queryByRole('combobox')).toBeNull();
  });

  it('signs out locally even when the revocation call fails', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(json(200, TENANT))
      .mockResolvedValueOnce(json(200, me('tenant_administrator')))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'));

    const user = userEvent.setup();
    render();
    await screen.findByRole('heading', { name: 'Acme Ltd' });
    await user.click(screen.getByRole('button', { name: /sign out/i }));

    // A reader who has decided to leave must not be kept signed in by a
    // network error.
    await waitFor(() => expect(hasSession('tenant')).toBe(false));
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeVisible();
  });

  it('gives the skip link somewhere to land', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(json(200, TENANT))
      .mockResolvedValueOnce(json(200, me('tenant_administrator')));

    render();
    await screen.findByRole('heading', { name: 'Acme Ltd' });

    const skip = screen.getByRole('link', { name: /skip to content/i });
    expect(skip).toHaveAttribute('href', '#main');
    expect(document.getElementById('main')).not.toBeNull();
  });
});
