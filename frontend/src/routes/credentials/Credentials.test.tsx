/**
 * The one-time secret is a modal, and it is gone once dismissed.
 *
 * §13's constraint is that it is "a modal, never a route", and the reason is
 * that a route holding a secret is a URL holding a secret — in history, in the
 * referer header, in whatever synced the address bar. These tests assert the
 * consequences: the secret never appears in the address, and once the reader
 * says they have copied it there is no way back to it.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { CredentialsRoute } from './Credentials';
import { ADMIN_ME, renderGuarded, respondWith } from '../../test/tenant';
import { resetSessionsForTest } from '../../api/session';

const USABLE = {
  key_id: '00000000-0000-4000-8000-0000000000aa',
  name: 'Nightly sync',
  visible_prefix: 'grk_live_abcd',
  scopes: ['catalog:write', 'events:write'],
  state: 'usable',
  status: 'active',
  expires_at: '2027-01-01T00:00:00Z',
  revoked_at: null,
  created_at: '2026-01-01T00:00:00Z',
  last_used_at: '2026-08-21T12:00:00Z',
  grace_expires_at: null,
  can_rotate: true,
  can_revoke: true,
  blocked_reason: null,
};

const REVOKED = {
  ...USABLE,
  key_id: '00000000-0000-4000-8000-0000000000bb',
  name: 'Old key',
  state: 'revoked',
  status: 'revoked',
  revoked_at: '2026-06-01T00:00:00Z',
  can_rotate: false,
  can_revoke: false,
  blocked_reason: 'This credential has already been revoked.',
};

const SCOPES = {
  scopes: [
    { scope: 'catalog:write', label: 'Send your catalogue', short_label: 'catalogue' },
    { scope: 'events:write', label: 'Send interactions', short_label: 'events' },
    {
      scope: 'recommendations:read',
      label: 'Ask for recommendations',
      short_label: 'recommendations',
    },
  ],
};

const ISSUED = {
  credential: { ...USABLE, key_id: '00000000-0000-4000-8000-0000000000cc', name: 'New key' },
  secret: 'grk_live_THISISTHEONLYTIMEYOUSEEIT',
  notice: 'This value is shown once.',
};

function render() {
  return renderGuarded('/credentials', <CredentialsRoute />, [
    'tenant_administrator',
    'tenant_developer',
  ]);
}

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
});

describe('/credentials', () => {
  it('takes each row’s controls from the server’s can_* fields', async () => {
    respondWith({
      '/v1/me': ADMIN_ME,
      '/v1/scopes': SCOPES,
      '/v1/api-keys': { credentials: [USABLE, REVOKED], total: 2 },
    });
    render();

    const rows = await screen.findAllByRole('row');
    const revokedRow = rows.find((row) => within(row).queryByText('Old key'));
    expect(revokedRow).toBeDefined();
    const rotate = within(revokedRow!).getByRole('button', { name: 'Rotate' });
    expect(rotate).toBeDisabled();
    expect(
      document.getElementById(rotate.getAttribute('aria-describedby')!),
    ).toHaveTextContent(/already been revoked/i);
  });

  it('shows the secret once, in a dialog, and never in the address', async () => {
    respondWith({
      '/v1/me': ADMIN_ME,
      '/v1/scopes': SCOPES,
      '/v1/api-keys': { credentials: [USABLE], total: 1 },
    });
    const { router } = render();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Create credential' }));
    await user.type(await screen.findByLabelText(/name/i), 'New key');
    await user.click(await screen.findByLabelText(/send your catalogue/i));

    vi.mocked(globalThis.fetch).mockImplementationOnce(() =>
      Promise.resolve(
        new Response(JSON.stringify(ISSUED), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    );
    await user.click(screen.getByRole('button', { name: 'Create' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(ISSUED.secret)).toBeVisible();
    expect(router.state.location.pathname + router.state.location.search).toBe('/credentials');
    expect(router.state.location.pathname).not.toContain('grk_live');

    // Dismissed, and unreachable afterwards: it was never in the cache and
    // there is no route that could show it again.
    await user.click(within(dialog).getByRole('button', { name: /copied/i }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.queryByText(ISSUED.secret)).toBeNull();
    expect(document.body.textContent).not.toContain(ISSUED.secret);
  });
});
