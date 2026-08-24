/**
 * The a11y pass. §13 rule 10, checked rather than asserted in a report.
 *
 * Three kinds of check, because no one of them catches what the others do:
 *
 * 1. **axe over a rendered page from each shell.** This is the broad sweep —
 *    unlabelled controls, tables without headers, headings out of order, a
 *    landmark named twice. It runs on the real route tree with real loaders.
 *
 * 2. **The dialog trap, driven by keyboard.** axe cannot see focus behaviour;
 *    it can only see that `aria-modal` is set, which is the easy half. Tab
 *    cycling and focus restoration are what a keyboard user actually needs.
 *
 * 3. **The stylesheets, read as text.** jsdom applies no CSS, so axe's colour
 *    and focus-appearance rules cannot run at all. A visible focus ring is a
 *    stylesheet fact, so it is checked as one — and the check that matters is
 *    that nothing removes an outline without putting something back.
 *
 * `color-contrast` is disabled in the axe runs for the same reason: it needs
 * layout and computed colour, and in jsdom every element resolves to
 * transparent-on-transparent, which axe reports as "incomplete" rather than
 * as a pass. The two themes are covered instead by `styles/tokens.test.ts`,
 * which checks that both define the same vocabulary.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import axe from 'axe-core';
import type { Result } from 'axe-core';
import { QueryClient } from '@tanstack/react-query';
import { renderRoutes } from './test/harness';
import { json } from './test/tenant';
import { routeTable } from './router';
import { resetSessionsForTest, store } from './api/session';

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

const USERS = {
  users: [
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
  ],
  total: 1,
};

const PLANS = {
  plans: [
    {
      plan_id: '55555555-5555-4555-8555-555555555555',
      plan_code: 'growth',
      plan_name: 'Growth',
      description: 'For teams past the first integration.',
      event_limit: 5_000_000,
      recommendation_limit: 2_000_000,
      training_limit: 60,
      product_limit: 250_000,
      storage_limit_bytes: 53_687_091_200,
      accepts_assignments: true,
      assigned_tenants: 3,
    },
  ],
};

const OPERATOR = {
  platform_user_id: '33333333-3333-4333-8333-333333333333',
  email: 'ops@graphrec.test',
  display_name: 'Ops Person',
  permissions: ['platform', 'plan_management'],
};

function serve(table: Record<string, unknown>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(typeof input === 'string' ? input : input instanceof URL ? input : input.url);
      const path = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0] ?? '';
      const body = table[path];
      if (body === undefined) {
        return json(404, { class: 'not_found', code: 'not_found', reason: 'No.' });
      }
      return json(200, body);
    }),
  );
}

function renderApp(entry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderRoutes(routeTable(queryClient), [entry], queryClient);
}

/**
 * Runs axe and returns the violations, formatted so a failure names the rule
 * and the element rather than dumping a result object.
 */
async function violations(container: HTMLElement): Promise<string[]> {
  const result = await axe.run(container, {
    rules: {
      // See the header: jsdom computes no colour, so this rule can only ever
      // report "incomplete", which axe surfaces as neither pass nor fail.
      'color-contrast': { enabled: false },
    },
  });
  return result.violations.map(
    (violation: Result) =>
      `${violation.id}: ${violation.nodes.map((node) => node.html).join(' | ')}`,
  );
}

beforeEach(() => {
  resetSessionsForTest();
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ------------------------------------------------------------------- axe

describe('axe finds nothing on a page from each shell', () => {
  it('the public shell — /login', async () => {
    serve({});
    const { container } = renderApp('/login');
    await screen.findByRole('button', { name: /Sign in/i });
    expect(await violations(container)).toEqual([]);
  });

  it('the tenant shell — /users, with its table and filters', async () => {
    store('tenant', SESSION);
    serve({ '/v1/tenant': TENANT, '/v1/me': ADMIN_ME, '/v1/users': USERS });
    const { container } = renderApp('/users');
    await screen.findByRole('heading', { name: 'Users', level: 1 });
    expect(await violations(container)).toEqual([]);
  });

  it('the platform shell — /admin/plans', async () => {
    store('platform', SESSION);
    serve({ '/v1/platform/me': OPERATOR, '/v1/platform/plans': PLANS });
    const { container } = renderApp('/admin/plans');
    await screen.findByRole('heading', { name: 'Plans', level: 1 });
    expect(await violations(container)).toEqual([]);
  });

  it('a standalone error page — /404', async () => {
    serve({});
    const { container } = renderApp('/404');
    await screen.findByRole('heading', { level: 1 });
    expect(await violations(container)).toEqual([]);
  });

  it('a page with a dialog open', async () => {
    store('tenant', SESSION);
    serve({ '/v1/tenant': TENANT, '/v1/me': ADMIN_ME, '/v1/users': USERS });
    const user = userEvent.setup();
    const { container } = renderApp('/users');
    await screen.findByRole('heading', { name: 'Users', level: 1 });
    await user.click(screen.getByRole('button', { name: 'Invite user' }));
    await screen.findByRole('dialog');
    expect(await violations(container)).toEqual([]);
  });
});

// --------------------------------------------------------- the focus trap

describe('a dialog traps focus and gives it back', () => {
  async function openInviteDialog() {
    store('tenant', SESSION);
    serve({ '/v1/tenant': TENANT, '/v1/me': ADMIN_ME, '/v1/users': USERS });
    const user = userEvent.setup();
    renderApp('/users');
    await screen.findByRole('heading', { name: 'Users', level: 1 });
    const opener = screen.getByRole('button', { name: 'Invite user' });
    await user.click(opener);
    const dialog = await screen.findByRole('dialog');
    return { user, opener, dialog };
  }

  it('moves focus into the dialog on open', async () => {
    const { dialog } = await openInviteDialog();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it('keeps Tab inside it, however long you hold Tab down', async () => {
    const { user, dialog } = await openInviteDialog();
    const focusable = within(dialog).getAllByRole('button').length + 3;
    // Round the ring twice. Once would pass on a trap that only wrapped the
    // last element; the failure this guards against is the one where focus
    // escapes on the *second* pass, into the page behind the scrim.
    for (let step = 0; step < focusable * 2; step += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it('keeps Shift+Tab inside it too', async () => {
    const { user, dialog } = await openInviteDialog();
    for (let step = 0; step < 8; step += 1) {
      await user.tab({ shift: true });
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it('returns focus to whatever opened it', async () => {
    const { user, opener } = await openInviteDialog();
    await user.keyboard('{Escape}');
    expect(await screen.findByRole('button', { name: 'Invite user' })).toBe(opener);
    expect(document.activeElement).toBe(opener);
  });
});

// ------------------------------------------------- keyboard reachability

describe('everything interactive is reachable', () => {
  it('puts no control out of the tab order and uses no positive tabindex', async () => {
    store('tenant', SESSION);
    serve({ '/v1/tenant': TENANT, '/v1/me': ADMIN_ME, '/v1/users': USERS });
    const { container } = renderApp('/users');
    await screen.findByRole('heading', { name: 'Users', level: 1 });

    const controls = [...container.querySelectorAll('a[href], button, input, select, textarea')];
    expect(controls.length).toBeGreaterThan(5);

    const removed = controls
      .filter((control) => control.getAttribute('tabindex') === '-1')
      .map((control) => control.outerHTML);
    expect(removed).toEqual([]);

    // A positive tabindex reorders the whole document, not just the element
    // carrying it, and the reorder is invisible to whoever adds the next
    // control. There is never a good reason.
    const reordered = [...container.querySelectorAll('[tabindex]')]
      .filter((element) => Number(element.getAttribute('tabindex')) > 0)
      .map((element) => element.outerHTML);
    expect(reordered).toEqual([]);
  });
});

// ------------------------------------------------------ the focus ring

describe('focus is visible', () => {
  const STYLES = join(dirname(fileURLToPath(import.meta.url)), 'styles');

  function sheets(): [string, string][] {
    return readdirSync(STYLES)
      .filter((name) => name.endsWith('.css'))
      .map((name) => [name, readFileSync(join(STYLES, name), 'utf8')]);
  }

  it('defines a focus-visible ring', () => {
    const all = sheets().map(([, source]) => source).join('\n');
    expect(all).toMatch(/:focus-visible/);
    expect(all).toMatch(/outline(-offset)?\s*:/);
  });

  it('never removes an outline without replacing it', () => {
    const offenders = sheets().flatMap(([name, source]) =>
      blindedBlocks(source).map((block) => `${name}: ${block}`),
    );
    expect(offenders).toEqual([]);
  });

  // The lint checking itself. Two literals, so the rule can never go vacuous
  // the way it did twice while being written: once because `\s*` before a
  // negative lookahead backtracks to zero width and matched the space in
  // `outline: none`, and once because the selector's own colon — `:focus` —
  // was read as a declaration separator. Both versions reported success over a
  // deliberately planted violation, which is the worst thing a lint can do.
  it('is a lint that bites', () => {
    expect(blindedBlocks('.a:focus { outline: none; }')).toEqual(['.a:focus { outline: none;']);
    expect(blindedBlocks('.a:focus { outline: 0; }')).toHaveLength(1);
    expect(blindedBlocks('.a:focus { outline: none; box-shadow: 0 0 0 2px blue; }')).toEqual([]);
    expect(blindedBlocks('.a:focus-visible { outline: 2px solid currentColor; }')).toEqual([]);
    expect(blindedBlocks('.a { color: red; }')).toEqual([]);
  });
});

/**
 * Blocks that take the focus ring away and put nothing back.
 *
 * `outline: none` is the single most common way a console loses its keyboard
 * affordance, and it is nearly always written to tidy up a default ring that a
 * `:focus-visible` rule was about to replace anyway. Allowed only where the
 * same block sets a `box-shadow` or a second `outline` with a real value.
 */
function blindedBlocks(css: string): string[] {
  return css
    .split('}')
    .filter((block) => {
      // The declarations only: everything before the last `{` is the selector,
      // and a selector contains colons of its own.
      const body = block.slice(block.lastIndexOf('{') + 1);
      const declarations = body.split(';').flatMap((declaration) => {
        const colon = declaration.indexOf(':');
        return colon < 0
          ? []
          : [
              [declaration.slice(0, colon).trim(), declaration.slice(colon + 1).trim()] as [
                string,
                string,
              ],
            ];
      });
      const gone = (value: string) => /^(none|0)$/.test(value);
      const removes = declarations.some(([name, value]) => name === 'outline' && gone(value));
      if (!removes) return false;
      return !declarations.some(
        ([name, value]) => name === 'box-shadow' || (name === 'outline' && !gone(value)),
      );
    })
    .map((block) => block.trim());
}
