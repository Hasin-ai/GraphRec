import { Outlet, useNavigate, useRouteLoaderData } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Sidebar } from '../ui';
import type { PlatformMe } from '../api/hooks/identity';
import { platformSignOut } from '../api/hooks/auth';
import { platformNav } from './nav';
import { ThemeToggle } from './ThemeToggle';

export const PLATFORM_ROOT_ID = 'platform-root';

export function usePlatformContext(): PlatformMe {
  return useRouteLoaderData(PLATFORM_ROOT_ID) as PlatformMe;
}

/**
 * The platform shell. Separate realm, separate sidebar, and — §6, explicitly —
 * **no tenant switcher**: for an operator a tenant is a filter over a list, not
 * a scope they enter. A switcher would imply the operator becomes that tenant,
 * which is exactly the confusion the two-realm split exists to prevent.
 *
 * The sidebar shows only what this operator's permissions open. That is a
 * courtesy over the route guards, not a replacement for them.
 */
export function PlatformLayout() {
  const operator = usePlatformContext();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  function handleSignOut() {
    platformSignOut();
    queryClient.clear();
    navigate('/admin/login', { replace: true });
  }

  return (
    <div className="shell">
      <Sidebar
        scopeLabel="Platform"
        groups={platformNav(operator.permissions)}
        foot={<span className="muted">platform administrator</span>}
      />
      <div className="shell__main">
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <header className="topbar">
          <div className="topbar__identity">
            <span className="topbar__name">{operator.display_name}</span>
            <span className="muted">{operator.email}</span>
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
