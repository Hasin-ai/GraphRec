/**
 * One full workflow per role, walked through the real route table.
 *
 * §14 asks for exactly this, and the reason it is worth having on top of the
 * per-page tests is that these three are the only tests that exercise the
 * *table*: a route registered under the wrong layout, a guard given the wrong
 * permission, or a mutation that never invalidates the list it changed all
 * pass every unit test in this repo and fail here.
 *
 * So they import `routeTable` — the same array `createRouter` hands to the
 * browser — rather than assembling routes of their own. A workflow test with
 * its own route table would be testing a console that does not ship.
 *
 * The server is a small state machine rather than a fixed table of responses,
 * because half of what is being checked is that the console re-reads after it
 * writes. A mock that returned the same list before and after the POST would
 * make an un-invalidated query look correct.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient } from '@tanstack/react-query';
import { renderRoutes } from '../test/harness';
import { json } from '../test/tenant';
import { routeTable } from '../router';
import { resetSessionsForTest, store } from '../api/session';

const SESSION = {
  access_token: 'access-1',
  expires_at: '2099-01-01T00:15:00Z',
  refresh_token: 'refresh-1',
  refresh_expires_at: '2099-01-08T00:00:00Z',
};

const TENANT = {
  tenant_id: '11111111-1111-4111-8111-111111111111',
  tenant_code: 'acme',
  tenant_name: 'Acme',
  status: 'active',
  plan_code: 'growth',
  created_at: '2026-01-01T00:00:00Z',
  status_reason: null,
};

const ADMIN_ME = {
  tenant_user_id: '00000000-0000-4000-8000-000000000001',
  tenant_id: TENANT.tenant_id,
  email: 'admin@acme.test',
  display_name: 'Ada Admin',
  role: 'tenant_administrator',
  status: 'active',
};

const DEVELOPER_ME = { ...ADMIN_ME, role: 'tenant_developer', display_name: 'Dev Devlin' };

const ONBOARDING = { steps: [], completed: 0, total: 0 };

/** A route with no data of its own still needs `/v1/onboarding` for `/home`. */
type Handler = (request: { method: string; url: string; body: unknown }) => unknown;

/**
 * Serves the routes a workflow touches and 404s everything else.
 *
 * The 404 is deliberate rather than a permissive fallback: an unexpected
 * request is a page fetching something the workflow did not intend, and it
 * should show up as a failing assertion rather than as a silent 200.
 */
function serve(routes: [string, Handler][]): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(typeof input === 'string' ? input : input instanceof URL ? input : input.url);
      const method = (init?.method ?? 'GET').toUpperCase();
      const path = url.replace(/^https?:\/\/[^/]+/, '');
      const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined;
      for (const [key, handler] of routes) {
        const [wantMethod, pattern] = key.split(' ') as [string, string];
        if (wantMethod !== method) continue;
        if (!new RegExp(`^${pattern}$`).test(path.split('?')[0] ?? path)) continue;
        const result = handler({ method, url: path, body });
        return result instanceof Response ? result : json(200, result);
      }
      throw new Error(`workflow made an unexpected request: ${method} ${path}`);
    }),
  );
}

function renderApp(entry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderRoutes(routeTable(queryClient), [entry], queryClient);
}

beforeEach(() => {
  resetSessionsForTest();
  vi.unstubAllGlobals();
});

// ------------------------------------------------------------------------
describe('the Tenant Administrator invites a colleague', () => {
  it('walks /home → /users → invite → the new row', async () => {
    store('tenant', SESSION);
    const users: Record<string, unknown>[] = [
      {
        tenant_user_id: ADMIN_ME.tenant_user_id,
        email: ADMIN_ME.email,
        display_name: ADMIN_ME.display_name,
        role: 'tenant_administrator',
        status: 'active',
        created_at: '2026-01-01T00:00:00Z',
        last_authenticated_at: '2026-08-20T09:00:00Z',
        is_last_active_administrator: true,
      },
    ];

    serve([
      ['GET /v1/tenant', () => TENANT],
      ['GET /v1/me', () => ADMIN_ME],
      ['GET /v1/onboarding', () => ONBOARDING],
      ['GET /v1/users', () => ({ users, total: users.length })],
      [
        'POST /v1/users',
        ({ body }) => {
          const sent = body as { email: string; display_name: string; role: string };
          users.push({
            tenant_user_id: '00000000-0000-4000-8000-000000000002',
            email: sent.email,
            display_name: sent.display_name,
            role: sent.role,
            status: 'invited',
            created_at: '2026-08-24T10:00:00Z',
            last_authenticated_at: null,
            is_last_active_administrator: false,
          });
          return {
            invitation_id: '44444444-4444-4444-8444-444444444444',
            invitation_token: 'invite-token-shown-once',
            expires_at: '2026-08-31T10:00:00Z',
            user: users[users.length - 1],
          };
        },
      ],
    ]);

    const user = userEvent.setup();
    renderApp('/home');

    // The sidebar is drawn from the role, so getting there by clicking is
    // itself the assertion that an administrator is offered Users. Scoped to
    // the nav landmark because `/home` also links there from its launcher —
    // and both being present is the correct behaviour, not a duplicate.
    const nav = within(await screen.findByRole('navigation', { name: 'Primary' }));
    await user.click(nav.getByRole('link', { name: 'Users' }));
    expect(await screen.findByRole('heading', { name: 'Users', level: 1 })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Invite user' }));
    await user.type(screen.getByLabelText(/Email/), 'bee@acme.test');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));

    // The one-time token is a modal, shown once, never a route (§13). It is
    // shown *inside* an invitation link, so the assertion is on the field's
    // value rather than on bare text.
    expect(await screen.findByText(/invite-token-shown-once/)).toBeInTheDocument();
    // Shown once and never addressable: the token is in a copy field, not in
    // the URL bar of a route somebody could bookmark or share by accident.
    expect(window.location.pathname).not.toContain('invite-token');

    await user.click(screen.getByRole('button', { name: 'I have sent it' }));

    // And the list re-read itself. This is the assertion a missing
    // `invalidateQueries` fails.
    //
    // By the row's *link*, because the address appears twice in it: no display
    // name was typed, and the dialog sends the email as the name rather than a
    // blank — which is the behaviour, not an accident of the fixture.
    const row = await screen.findByRole('link', { name: 'bee@acme.test' });
    expect(within(row.closest('tr') as HTMLElement).getByText('invited')).toBeInTheDocument();
  });
});

// ------------------------------------------------------------------------
describe('the Tenant Developer adds a product', () => {
  it('walks /products → new → the product page', async () => {
    store('tenant', SESSION);
    const products: Record<string, unknown>[] = [];

    const asRow = (product: Record<string, unknown>) => ({
      ...product,
      eligible: false,
      ineligibility_reason: 'Not yet in an activated model version.',
    });

    serve([
      ['GET /v1/tenant', () => TENANT],
      ['GET /v1/me', () => DEVELOPER_ME],
      ['GET /v1/onboarding', () => ONBOARDING],
      [
        'GET /v1/products',
        () => ({ products: products.map(asRow), total: products.length, limit: 25, offset: 0 }),
      ],
      [
        'GET /v1/products/[^/]+',
        ({ url }) => {
          const id = decodeURIComponent(url.split('/').pop() ?? '');
          const found = products.find((product) => product.external_id === id);
          return found
            ? asRow(found)
            : json(404, { class: 'not_found', code: 'not_found', reason: 'No such product.' });
        },
      ],
      [
        'POST /v1/products',
        ({ body }) => {
          const sent = body as Record<string, unknown>;
          const created = { ...sent, updated_at: '2026-08-24T10:00:00Z' };
          products.push(created);
          return asRow(created);
        },
      ],
    ]);

    const user = userEvent.setup();
    renderApp('/products');

    await screen.findByRole('heading', { name: 'Catalogue', level: 1 });
    await user.click(screen.getByRole('button', { name: 'Add product' }));

    await user.type(await screen.findByLabelText(/Your product ID/), 'sku-1');
    await user.type(screen.getByLabelText(/^Title/), 'A Widget');
    await user.click(screen.getByRole('button', { name: 'Add product' }));

    // Landed on the product's own page, addressed by *its* identifier — and
    // still no tenant identifier anywhere in the path (§13).
    expect(await screen.findByRole('heading', { name: 'A Widget', level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).not.toContain(TENANT.tenant_id);
  });
});

// ------------------------------------------------------------------------
describe('the platform operator suspends a tenant', () => {
  it('walks /admin → /admin/tenants → the tenant → suspended', async () => {
    store('platform', SESSION);
    const tenant = {
      tenant_id: '22222222-2222-4222-8222-222222222222',
      tenant_code: 'globex',
      tenant_name: 'Globex',
      status: 'active',
      plan_code: 'growth',
      created_at: '2026-02-01T00:00:00Z',
    };

    const detail = () => ({
      tenant,
      sections: {
        status: {
          granted: true,
          reason: null,
          data: {
            status: tenant.status,
            status_reason: null,
            status_changed_at: '2026-02-01T00:00:00Z',
            is_operable: tenant.status === 'active',
          },
        },
        // Withheld, and the route still renders. Gating the whole page on all
        // three permissions is exactly the mistake §8 warns against.
        plan: { granted: false, reason: 'Plan management is not granted to this account.', data: null },
        usage: { granted: false, reason: 'Platform scope is not granted to this account.', data: null },
      },
    });

    serve([
      [
        'GET /v1/platform/me',
        () => ({
          platform_user_id: '33333333-3333-4333-8333-333333333333',
          email: 'ops@graphrec.test',
          display_name: 'Ops Person',
          permissions: ['platform'],
        }),
      ],
      [
        'GET /v1/platform/tenants',
        () => ({ tenants: [tenant], total: 1, limit: 25, offset: 0 }),
      ],
      ['GET /v1/platform/tenants/[^/:]+', () => detail()],
      [
        'POST /v1/platform/tenants/[^/]+:change-status',
        ({ body }) => {
          const sent = body as { status: string };
          tenant.status = sent.status;
          return tenant;
        },
      ],
    ]);

    const user = userEvent.setup();
    renderApp('/admin');

    // `/admin` is a redirect to the first *permitted* route, and this operator
    // holds only `platform`.
    expect(await screen.findByRole('heading', { name: 'Tenants', level: 1 })).toBeInTheDocument();

    await user.click(await screen.findByRole('link', { name: 'Globex' }));
    await screen.findByRole('heading', { name: 'Globex', level: 1 });

    // The two withheld sections state the server's reason rather than 403ing
    // the page out from under an operator entitled to be here.
    expect(screen.getByText(/Plan management is not granted/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Change status' }));
    const dialog = within(await screen.findByRole('dialog'));
    await user.selectOptions(dialog.getByLabelText('New status'), 'suspended');
    // The reason is required and short reasons are refused, because the status,
    // the actor and the time are mechanical and this is the only part a person
    // writes. The confirm button is disabled until it is there.
    await user.type(dialog.getByLabelText(/Reason/), 'Non-payment, escalated twice.');
    await user.click(dialog.getByRole('button', { name: 'Change status' }));

    await waitFor(() =>
      expect(within(screen.getByRole('main')).getByText('suspended')).toBeInTheDocument(),
    );
  });
});
