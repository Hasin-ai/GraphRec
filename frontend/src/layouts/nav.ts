/**
 * What each sidebar offers, and the one fact that decides whether an entry is
 * offered at all.
 *
 * The permission attached to each platform entry is the permission the *server*
 * requires on that route's endpoint (`apps/control_api/routers/platform.py`),
 * not a second opinion about who ought to see it. Where the two could drift
 * apart, this table is the one that is wrong: the loader re-checks, and the
 * endpoint re-checks after that. Hiding a link is a courtesy; the guard is the
 * rule (§13).
 */

import type { NavGroup } from '../ui';
import type { PlatformPermission, TenantRole } from '../lib/enums';

interface RoleNavItem {
  to: string;
  label: string;
  end?: boolean;
  roles: readonly TenantRole[];
}

const BOTH: readonly TenantRole[] = ['tenant_administrator', 'tenant_developer'];
const ADMIN: readonly TenantRole[] = ['tenant_administrator'];
const DEVELOPER: readonly TenantRole[] = ['tenant_developer'];

/**
 * §4's role split, transcribed. The Tenant Administrator having no catalogue
 * access is intentional and comes from the use-case diagrams, so `Products` and
 * `Submit events` are developer-only even though an administrator can do
 * strictly more nearly everywhere else.
 */
const TENANT_NAV: readonly { label: string; items: readonly RoleNavItem[] }[] = [
  {
    label: 'Workspace',
    items: [{ to: '/home', label: 'Home', end: true, roles: BOTH }],
  },
  {
    label: 'Catalogue and events',
    items: [
      { to: '/products', label: 'Products', roles: DEVELOPER },
      { to: '/events/submit', label: 'Submit events', roles: DEVELOPER },
    ],
  },
  {
    label: 'Model',
    items: [
      { to: '/training', label: 'Training', roles: ADMIN },
      { to: '/models', label: 'Models', roles: ADMIN },
    ],
  },
  {
    label: 'Integration',
    items: [
      { to: '/credentials', label: 'Credentials', roles: BOTH },
      { to: '/integration', label: 'API reference', roles: BOTH },
    ],
  },
  {
    label: 'Operations',
    items: [
      { to: '/usage', label: 'Usage', roles: ADMIN },
      { to: '/service-status', label: 'Service status', roles: ADMIN },
    ],
  },
  {
    label: 'Administration',
    items: [
      { to: '/users', label: 'Users', roles: ADMIN },
      { to: '/audit', label: 'Audit', roles: ADMIN },
      { to: '/account', label: 'Account', roles: BOTH },
    ],
  },
];

interface PermissionNavItem {
  to: string;
  label: string;
  end?: boolean;
  permission: PlatformPermission;
}

const PLATFORM_NAV: readonly { label: string; items: readonly PermissionNavItem[] }[] = [
  {
    label: 'Estate',
    items: [
      { to: '/admin/tenants', label: 'Tenants', permission: 'platform' },
      { to: '/admin/plans', label: 'Plans', permission: 'plan_management' },
    ],
  },
  {
    label: 'Oversight',
    items: [
      { to: '/admin/usage', label: 'Usage', permission: 'platform_scope' },
      { to: '/admin/status', label: 'Installation health', permission: 'monitoring' },
      { to: '/admin/audit', label: 'Failures and audit', permission: 'audit' },
    ],
  },
];

function toNavItem({ to, label, end }: { to: string; label: string; end?: boolean }) {
  return { to, label, ...(end === undefined ? {} : { end }) };
}

/** Empty groups are dropped, so a Developer sees no "Operations" heading with nothing under it. */
export function tenantNav(role: TenantRole): NavGroup[] {
  return TENANT_NAV.map((group) => ({
    label: group.label,
    items: group.items.filter((item) => item.roles.includes(role)).map(toNavItem),
  })).filter((group) => group.items.length > 0);
}

export function platformNav(permissions: readonly PlatformPermission[]): NavGroup[] {
  return PLATFORM_NAV.map((group) => ({
    label: group.label,
    items: group.items.filter((item) => permissions.includes(item.permission)).map(toNavItem),
  })).filter((group) => group.items.length > 0);
}

/**
 * Where `/admin` sends an operator: the first route their permissions open.
 *
 * An operator holding only `audit` lands on `/admin/audit`. One holding nothing
 * lands nowhere and gets `/403`, which is the only honest answer for an account
 * with no permissions at all.
 */
export function firstPermittedPlatformRoute(
  permissions: readonly PlatformPermission[],
): string | null {
  for (const group of PLATFORM_NAV) {
    for (const item of group.items) {
      if (permissions.includes(item.permission)) return item.to;
    }
  }
  return null;
}
