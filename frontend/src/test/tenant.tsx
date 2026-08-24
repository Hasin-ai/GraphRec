/**
 * Shared scaffolding for tenant-route tests.
 *
 * Every one of these tests renders through the real router with real loaders,
 * for the reason the harness docstring gives: a test that mounted a page
 * component directly would be testing the page with its guards removed.
 */

import { vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import type { RouteObject } from 'react-router-dom';
import { renderRoutes } from './harness';
import { RouteErrorBoundary } from '../routes/errors/RouteErrorBoundary';
import { requireRoleLoader } from '../guards';
import { store } from '../api/session';
import type { TenantRole } from '../lib/enums';

export const SESSION = {
  access_token: 'access-1',
  expires_at: '2099-01-01T00:15:00Z',
  refresh_token: 'refresh-1',
  refresh_expires_at: '2099-01-08T00:00:00Z',
};

export const ADMIN_ME = {
  tenant_user_id: '00000000-0000-4000-8000-000000000001',
  tenant_id: '11111111-1111-4111-8111-111111111111',
  email: 'admin@acme.test',
  display_name: 'Ada Admin',
  role: 'tenant_administrator',
  status: 'active',
};

export const DEVELOPER_ME = { ...ADMIN_ME, role: 'tenant_developer', display_name: 'Dev Devlin' };

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/**
 * Answers each request from a table keyed by path prefix, in declaration order.
 *
 * Routes in this console fetch several endpoints at once and React Query does
 * not promise an order, so `mockResolvedValueOnce` chains are a source of
 * tests that pass until somebody adds a query. Matching on the URL does not
 * have that problem.
 */
export function respondWith(table: Record<string, unknown>, status = 200): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(typeof input === 'string' ? input : input instanceof URL ? input : input.url);
      for (const [prefix, body] of Object.entries(table)) {
        if (url.startsWith(prefix)) {
          return Promise.resolve(
            body instanceof Response ? body.clone() : json(status, body),
          );
        }
      }
      return Promise.resolve(json(404, { class: 'not_found', code: 'not_found', reason: 'No.' }));
    }),
  );
}

/**
 * One role-guarded route, behind the same error boundary the layouts mount.
 *
 * The boundary is the point: gate 3 throws a bare `Response`, and what turns
 * that into the 403 page is `RouteErrorBoundary`. A test that asserted on the
 * thrown response instead would pass with the boundary deleted.
 */
export function renderGuarded(
  path: string,
  element: RouteObject['element'],
  allowed: readonly TenantRole[],
  entry = path,
) {
  store('tenant', SESSION);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderRoutes(
    [
      {
        errorElement: <RouteErrorBoundary />,
        children: [
          { path, loader: requireRoleLoader(queryClient, allowed), element },
          { path: '*', element: <div>elsewhere</div> },
        ],
      },
    ],
    [entry],
  );
}
