import { Outlet, useNavigate, useRouteLoaderData } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Sidebar } from '../ui';
import { TENANT_ROLE_LABELS } from '../lib/enums';
import type { TenantRole } from '../lib/enums';
import type { TenantContext } from '../guards';
import { signOut } from '../api/hooks/auth';
import { tenantNav } from './nav';
import { ThemeToggle } from './ThemeToggle';

export const TENANT_ROOT_ID = 'tenant-root';

/** The loader has already run gates 1 and 2, so this data is always present. */
export function useTenantContext(): TenantContext {
  return useRouteLoaderData(TENANT_ROOT_ID) as TenantContext;
}

/**
 * The signed-in tenant shell.
 *
 * There is no tenant switcher and no tenant selector anywhere in it. The tenant
 * comes from the session and from nowhere else (NR-NF-02), which is also why no
 * tenant-realm route carries a tenant identifier in its path — an identifier in
 * the address is an invitation to trust it.
 */
export function TenantLayout() {
  const { me, tenant } = useTenantContext();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function handleSignOut() {
    await signOut();
    // The cache holds this tenant's data. Leaving it behind would let the next
    // sign-in on this machine render the previous one's rows before its own
    // queries resolve.
    queryClient.clear();
    navigate('/login', { replace: true });
  }

  return (
    <div className="shell">
      <Sidebar
        scopeLabel={`Tenant · ${tenant.tenant_code}`}
        groups={tenantNav(me.role as TenantRole)}
        foot={<span className="muted">{TENANT_ROLE_LABELS[me.role as TenantRole]}</span>}
      />
      <div className="shell__main">
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="topbar">
          <div className="topbar__identity">
            <span className="topbar__name">{tenant.tenant_name}</span>
            <span className="muted">{me.email}</span>
          </div>
          <div className="topbar__actions">
            <ThemeToggle />
            <Button variant="secondary" size="sm" onClick={handleSignOut}>
              Sign out
            </Button>
          </div>
        </header>
        <main id="main" style={{ display: 'flex' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
