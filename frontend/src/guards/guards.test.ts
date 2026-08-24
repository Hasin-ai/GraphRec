import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import {
  platformGuard,
  requireRole,
  rethrowAsRouteError,
  tenantGuard,
  tenantStatusGuard,
} from './index';
import { resetSessionsForTest, store } from '../api/session';
import { ApiError } from '../api/errors';

const SESSION = {
  access_token: 'access-1',
  expires_at: '2026-01-01T00:15:00Z',
  refresh_token: 'refresh-1',
  refresh_expires_at: '2026-01-08T00:00:00Z',
};

const ACTIVE_TENANT = {
  tenant_id: '11111111-1111-1111-1111-111111111111',
  tenant_code: 'acme',
  tenant_name: 'Acme',
  status: 'active',
  plan_code: 'standard',
  status_reason: null,
  created_at: '2026-01-01T00:00:00Z',
};

const ADMIN = {
  tenant_user_id: '22222222-2222-2222-2222-222222222222',
  tenant_id: ACTIVE_TENANT.tenant_id,
  email: 'admin@acme.test',
  display_name: 'Admin',
  role: 'tenant_administrator' as const,
  status: 'active',
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function route(path: string): Request {
  return new Request(`http://localhost:3000${path}`);
}

/** Loaders signal navigation by throwing a `Response`; this reads where to. */
async function locationOfThrow(run: () => Promise<unknown>): Promise<string | null> {
  try {
    await run();
  } catch (thrown) {
    if (thrown instanceof Response) return thrown.headers.get('Location');
    throw thrown;
  }
  return null;
}

let queryClient: QueryClient;

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
  vi.stubGlobal('fetch', vi.fn());
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe('gate 1 — identity', () => {
  it('sends an unauthenticated caller to /login, carrying where they were going', async () => {
    const to = await locationOfThrow(() => tenantGuard(queryClient, route('/training/abc?tab=log')));
    expect(to).toBe(`/login?next=${encodeURIComponent('/training/abc?tab=log')}`);
  });

  it('sends an unauthenticated platform caller to the platform form, not the tenant one', async () => {
    const to = await locationOfThrow(() => platformGuard(queryClient, route('/admin/tenants')));
    expect(to).toBe(`/admin/login?next=${encodeURIComponent('/admin/tenants')}`);
  });

  it('does not fetch anything before deciding there is no session', async () => {
    await locationOfThrow(() => tenantGuard(queryClient, route('/home')));
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});

describe('gate 2 — tenant state', () => {
  it('sends a member of a non-active tenant to the status page', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      json(200, { ...ACTIVE_TENANT, status: 'suspended', status_reason: 'Unpaid invoice' }),
    );

    const to = await locationOfThrow(() => tenantGuard(queryClient, route('/home')));
    expect(to).toBe('/account/tenant-status');
  });

  it('stops before reading /v1/me, which gate 2 would refuse anyway', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      json(200, { ...ACTIVE_TENANT, status: 'pending' }),
    );

    await locationOfThrow(() => tenantGuard(queryClient, route('/home')));

    const urls = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url));
    expect(urls).toEqual(['/v1/tenant']);
  });

  it('lets an active tenant through with both reads', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(json(200, ACTIVE_TENANT))
      .mockResolvedValueOnce(json(200, ADMIN));

    await expect(tenantGuard(queryClient, route('/home'))).resolves.toEqual({
      me: ADMIN,
      tenant: ACTIVE_TENANT,
    });
  });

  it('does not strand a reader on the status page once the tenant is active', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, ACTIVE_TENANT));

    const to = await locationOfThrow(() =>
      tenantStatusGuard(queryClient, route('/account/tenant-status')),
    );
    expect(to).toBe('/home');
  });

  it('renders the status page for the state that sent them there', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      json(200, { ...ACTIVE_TENANT, status: 'suspended' }),
    );

    const tenant = await tenantStatusGuard(queryClient, route('/account/tenant-status'));
    expect(tenant.status).toBe('suspended');
  });
});

describe('gate 3 — role and permission', () => {
  it('refuses a role the route does not name', () => {
    expect(() => requireRole({ ...ADMIN, role: 'tenant_developer' }, ['tenant_administrator']))
      .toThrowError();
    try {
      requireRole({ ...ADMIN, role: 'tenant_developer' }, ['tenant_administrator']);
    } catch (thrown) {
      expect(thrown).toBeInstanceOf(Response);
      expect((thrown as Response).status).toBe(403);
    }
  });

  it('admits a role the route does name', () => {
    expect(() => requireRole(ADMIN, ['tenant_administrator', 'tenant_developer'])).not.toThrow();
  });

  it('refuses a platform operator who does not hold the permission the route needs', async () => {
    store('platform', SESSION);
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      json(200, {
        platform_user_id: '33333333-3333-3333-3333-333333333333',
        email: 'ops@graphrec.test',
        display_name: 'Ops',
        permissions: ['monitoring'],
      }),
    );

    await expect(
      platformGuard(queryClient, route('/admin/plans'), 'plan_management'),
    ).rejects.toMatchObject({ status: 403 });
  });
});

describe('gate 4 — ownership', () => {
  it('turns a 404 into /404', () => {
    const notFound = new ApiError(404, {
      class: 'not_found',
      code: 'not_found',
      reason: 'Not found.',
      reference: 'err-1',
      field_errors: [],
      retryable: false,
      retry_after_seconds: null,
    });
    try {
      rethrowAsRouteError(notFound);
      expect.unreachable('should rethrow');
    } catch (thrown) {
      expect((thrown as Response).status).toBe(404);
    }
  });

  it('leaves anything that is not a gate outcome alone, rather than guessing', () => {
    const boom = new Error('kaboom');
    expect(() => rethrowAsRouteError(boom)).toThrowError(boom);
  });
});
