/**
 * The two claims `/users*` has to make good on:
 *
 * 1. gate 3 is a **route guard** — a developer who types the address is
 *    refused before the page renders, not shown a page with no buttons;
 * 2. gate 5 is **the server's answer** — the last active administrator's
 *    controls are disabled because `is_last_active_administrator` says so, and
 *    the explanation is announced to a keyboard user rather than hovered.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import { UsersRoute } from './Users';
import { UserDetailRoute } from './UserDetail';
import {
  ADMIN_ME,
  DEVELOPER_ME,
  renderGuarded,
  respondWith,
} from '../../test/tenant';
import { resetSessionsForTest } from '../../api/session';
import { requestUrl } from '../../test/request';

const LAST_ADMIN = {
  tenant_user_id: '00000000-0000-4000-8000-000000000001',
  email: 'admin@acme.test',
  display_name: 'Ada Admin',
  role: 'tenant_administrator',
  status: 'active',
  created_at: '2026-01-01T00:00:00Z',
  last_authenticated_at: '2026-08-20T09:00:00Z',
  is_last_active_administrator: true,
};

const DEVELOPER = {
  ...LAST_ADMIN,
  tenant_user_id: '00000000-0000-4000-8000-000000000002',
  email: 'dev@acme.test',
  display_name: 'Dev Devlin',
  role: 'tenant_developer',
  status: 'invited',
  last_authenticated_at: null,
  is_last_active_administrator: false,
};

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
});

describe('/users', () => {
  it('refuses a Tenant Developer at the route, before the list is fetched', async () => {
    respondWith({ '/v1/me': DEVELOPER_ME });
    renderGuarded('/users', <UsersRoute />, ['tenant_administrator']);

    expect(
      await screen.findByRole('heading', { name: /do not have access/i }),
    ).toBeVisible();
    const asked = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => requestUrl(url));
    expect(asked).toEqual(['/v1/me']);
  });

  it('lists users for an administrator', async () => {
    respondWith({
      '/v1/me': ADMIN_ME,
      '/v1/users': { users: [LAST_ADMIN, DEVELOPER], total: 2 },
    });
    renderGuarded('/users', <UsersRoute />, ['tenant_administrator']);

    expect(await screen.findByRole('link', { name: 'Ada Admin' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Dev Devlin' })).toBeVisible();
    // The badge, not the filter option of the same name.
    expect(within(screen.getByRole('table')).getByText('invited')).toBeVisible();
  });
});

describe('/users/:userId', () => {
  it('disables the last administrator’s controls from the server’s field', async () => {
    respondWith({ '/v1/me': ADMIN_ME, '/v1/users/': LAST_ADMIN });
    renderGuarded(
      '/users/:userId',
      <UserDetailRoute />,
      ['tenant_administrator'],
      `/users/${LAST_ADMIN.tenant_user_id}`,
    );

    const role = await screen.findByRole('button', { name: 'Change role' });
    const status = screen.getByRole('button', { name: 'Change status' });
    expect(role).toBeDisabled();
    expect(status).toBeDisabled();

    // The reason is *associated* with the control, not merely printed near it.
    // A `title` would be invisible to the reader most affected by it.
    const described = role.getAttribute('aria-describedby');
    expect(described).toBeTruthy();
    expect(document.getElementById(described!)).toHaveTextContent(
      /last active administrator/i,
    );
  });

  it('leaves them enabled when the server says somebody else can administer', async () => {
    respondWith({
      '/v1/me': ADMIN_ME,
      '/v1/users/': { ...LAST_ADMIN, is_last_active_administrator: false },
    });
    renderGuarded(
      '/users/:userId',
      <UserDetailRoute />,
      ['tenant_administrator'],
      `/users/${LAST_ADMIN.tenant_user_id}`,
    );

    expect(await screen.findByRole('button', { name: 'Change role' })).toBeEnabled();
  });

  it('offers resend only while the invitation is unaccepted', async () => {
    respondWith({ '/v1/me': ADMIN_ME, '/v1/users/': DEVELOPER });
    renderGuarded(
      '/users/:userId',
      <UserDetailRoute />,
      ['tenant_administrator'],
      `/users/${DEVELOPER.tenant_user_id}`,
    );

    expect(await screen.findByRole('button', { name: 'Resend invitation' })).toBeEnabled();
    expect(
      within(document.body).getByText(/only its digest was kept/i),
    ).toBeVisible();
  });

  it('renders a foreign or missing user as /404, naming nothing', async () => {
    respondWith({ '/v1/me': ADMIN_ME });
    renderGuarded(
      '/users/:userId',
      <UserDetailRoute />,
      ['tenant_administrator'],
      '/users/00000000-0000-4000-8000-00000000ffff',
    );

    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeVisible();
    expect(document.body.textContent).not.toMatch(/00000000-0000-4000-8000-00000000ffff/);
  });
});
