import { Outlet, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '../ui';
import { signOut } from '../api/hooks/auth';
import { ThemeToggle } from './ThemeToggle';

/**
 * Where gate 2 lands. The session is valid; the tenant is not operable.
 *
 * Navigation is suppressed (§6) rather than disabled: every destination is
 * behind the gate that sent the reader here, so a sidebar would be a list of
 * links that all come back to this page. Sign out stays, because leaving is the
 * one action still available.
 */
export function StateGateLayout() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  async function handleSignOut() {
    await signOut();
    queryClient.clear();
    void navigate('/login', { replace: true });
  }

  return (
    <div className="standalone">
      <div className="standalone__brand">GraphRec</div>
      <main id="main">
        <Outlet />
      </main>
      <div className="topbar__actions">
        <ThemeToggle />
        <Button variant="secondary" size="sm" onClick={handleSignOut}>
          Sign out
        </Button>
      </div>
    </div>
  );
}
