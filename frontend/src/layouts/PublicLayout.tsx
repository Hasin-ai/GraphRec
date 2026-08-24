import { Outlet } from 'react-router-dom';
import { ThemeToggle } from './ThemeToggle';

/**
 * Brand only. No navigation, because nothing is permitted yet (§6) — a menu on
 * an unauthenticated page is a list of places the reader will be refused.
 */
export function PublicLayout() {
  return (
    <div className="standalone">
      <div className="standalone__brand">GraphRec</div>
      <main id="main">
        <Outlet />
      </main>
      <ThemeToggle />
    </div>
  );
}
