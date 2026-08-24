/**
 * `/products` is the Tenant Developer's, and only theirs.
 *
 * §4's table gives the Tenant Administrator no catalogue access at all. That
 * looks like an oversight until you read the use-case diagrams it came from,
 * so it gets a test: an administrator typing `/products` is refused, and the
 * refusal happens at the route rather than by the page rendering empty.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import { ProductsRoute } from './Products';
import { ProductDetailRoute } from './ProductDetail';
import { ADMIN_ME, DEVELOPER_ME, renderGuarded, respondWith } from '../../test/tenant';
import { resetSessionsForTest } from '../../api/session';

const ELIGIBLE = {
  external_id: 'sku-1',
  title: 'A thing',
  description: null,
  category: 'things',
  brand: null,
  price: '19.99',
  availability: 'in_stock',
  active: true,
  attributes: {},
  eligible: true,
  ineligibility: null,
  exclusion_reason: null,
  blocked_reason: null,
  can_disable: true,
  disabled_at: null,
  disabled_reason: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

const INELIGIBLE = {
  ...ELIGIBLE,
  external_id: 'sku-2',
  title: 'A sold-out thing',
  availability: 'out_of_stock',
  eligible: false,
  ineligibility: 'Out of stock, so it is not recommended.',
  can_disable: false,
  disabled_at: '2026-07-01T00:00:00Z',
  disabled_reason: 'Discontinued.',
};

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
});

describe('/products', () => {
  it('refuses a Tenant Administrator, before the catalogue is fetched', async () => {
    respondWith({ '/v1/me': ADMIN_ME });
    renderGuarded('/products', <ProductsRoute />, ['tenant_developer']);

    expect(await screen.findByRole('heading', { name: /do not have access/i })).toBeVisible();
    expect(vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url))).toEqual([
      '/v1/me',
    ]);
  });

  it('takes eligibility and its explanation from the server', async () => {
    respondWith({
      '/v1/me': DEVELOPER_ME,
      '/v1/products': { products: [ELIGIBLE, INELIGIBLE], total: 2, limit: 25, offset: 0 },
    });
    renderGuarded('/products', <ProductsRoute />, ['tenant_developer']);

    const table = await screen.findByRole('table', { name: 'Products' });
    const row = within(table).getByRole('row', { name: /A sold-out thing/ });
    expect(within(row).getByText('no')).toBeVisible();
    expect(within(row).getByText('Out of stock, so it is not recommended.')).toBeVisible();

    const good = within(table).getByRole('row', { name: /A thing/ });
    expect(within(good).getByText('yes')).toBeVisible();
  });
});

describe('/products/:productId', () => {
  it('disables the disable control from can_disable, with a reason', async () => {
    respondWith({ '/v1/me': DEVELOPER_ME, '/v1/products/': INELIGIBLE });
    renderGuarded(
      '/products/:productId',
      <ProductDetailRoute />,
      ['tenant_developer'],
      '/products/sku-2',
    );

    const disable = await screen.findByRole('button', { name: 'Disable' });
    expect(disable).toBeDisabled();
    expect(
      document.getElementById(disable.getAttribute('aria-describedby')!),
    ).toHaveTextContent(/already disabled/i);
  });

  it('leads with the server’s ineligibility sentence', async () => {
    respondWith({ '/v1/me': DEVELOPER_ME, '/v1/products/': INELIGIBLE });
    renderGuarded(
      '/products/:productId',
      <ProductDetailRoute />,
      ['tenant_developer'],
      '/products/sku-2',
    );

    expect(
      await screen.findByText('Out of stock, so it is not recommended.'),
    ).toBeVisible();
  });

  it('renders a foreign product as /404 without naming it', async () => {
    respondWith({ '/v1/me': DEVELOPER_ME });
    renderGuarded(
      '/products/:productId',
      <ProductDetailRoute />,
      ['tenant_developer'],
      '/products/somebody-elses-sku',
    );

    expect(await screen.findByRole('heading', { name: 'Not found' })).toBeVisible();
    expect(document.body.textContent).not.toContain('somebody-elses-sku');
  });
});
