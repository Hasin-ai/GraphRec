import { describe, expect, it } from 'vitest';
import { firstPermittedPlatformRoute, platformNav, tenantNav } from './nav';

function destinations(groups: { items: readonly { to: string }[] }[]): string[] {
  return groups.flatMap((group) => group.items.map((item) => item.to));
}

describe('the tenant sidebar', () => {
  it('gives a Developer the catalogue and an Administrator none of it', () => {
    // §4, from the use-case diagrams: the Tenant Administrator has **no**
    // catalogue access, even though they can do strictly more elsewhere.
    expect(destinations(tenantNav('tenant_developer'))).toContain('/products');
    expect(destinations(tenantNav('tenant_administrator'))).not.toContain('/products');
  });

  it('gives an Administrator training, models and users, and a Developer none of them', () => {
    const developer = destinations(tenantNav('tenant_developer'));
    for (const admin of ['/training', '/models', '/users', '/audit', '/usage']) {
      expect(destinations(tenantNav('tenant_administrator'))).toContain(admin);
      expect(developer).not.toContain(admin);
    }
  });

  it('offers credentials, the API reference and the account to both', () => {
    for (const shared of ['/credentials', '/integration', '/account', '/home']) {
      expect(destinations(tenantNav('tenant_administrator'))).toContain(shared);
      expect(destinations(tenantNav('tenant_developer'))).toContain(shared);
    }
  });

  it('drops a group rather than showing an empty heading', () => {
    const labels = tenantNav('tenant_developer').map((group) => group.label);
    expect(labels).not.toContain('Operations');
    for (const group of tenantNav('tenant_developer')) {
      expect(group.items.length).toBeGreaterThan(0);
    }
  });

  it('names no tenant identifier in any destination', () => {
    // §13: no tenant-realm path may carry one. The sidebar is where such a
    // segment would first appear if anyone were tempted.
    for (const role of ['tenant_administrator', 'tenant_developer'] as const) {
      for (const to of destinations(tenantNav(role))) {
        expect(to).not.toMatch(/tenant/i);
      }
    }
  });
});

describe('the platform sidebar', () => {
  it('shows only what the held permissions open', () => {
    expect(destinations(platformNav(['monitoring']))).toEqual(['/admin/status']);
    expect(destinations(platformNav(['audit', 'plan_management']))).toEqual([
      '/admin/plans',
      '/admin/audit',
    ]);
  });

  it('shows nothing at all to an operator holding nothing', () => {
    expect(platformNav([])).toEqual([]);
  });

  it('sends /admin to the first route the operator may open', () => {
    expect(firstPermittedPlatformRoute(['platform', 'audit'])).toBe('/admin/tenants');
    expect(firstPermittedPlatformRoute(['audit'])).toBe('/admin/audit');
    expect(firstPermittedPlatformRoute(['monitoring'])).toBe('/admin/status');
  });

  it('sends an operator with no permissions nowhere, so /admin can answer 403', () => {
    expect(firstPermittedPlatformRoute([])).toBeNull();
  });
});
