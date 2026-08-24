import { NavLink } from 'react-router-dom';
import type { ReactNode } from 'react';

export interface NavItem {
  to: string;
  label: string;
  /** `end` for a route that is also a prefix of its children, e.g. `/products`. */
  end?: boolean;
}

export interface NavGroup {
  label: string;
  items: readonly NavItem[];
}

export interface SidebarProps {
  /** `Tenant · {name}` or `Platform`. Rendered in mono under the wordmark. */
  scopeLabel: string;
  groups: readonly NavGroup[];
  /** Service badges for the tenant shell; the platform shell passes none. */
  status?: ReactNode;
  foot?: ReactNode;
}

/**
 * The filtering happens above this component, not inside it: callers pass the
 * groups the session may enter. That is deliberate — a sidebar that decided
 * for itself would be a second authorization implementation living next to the
 * route guards, and the two would eventually disagree. §13 is explicit that
 * navigation is not the guard; hiding a link is a courtesy, the loader is the
 * rule.
 */
export function Sidebar({ scopeLabel, groups, status, foot }: SidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <div className="sidebar__wordmark">GraphRec</div>
        <div className="sidebar__scope">{scopeLabel}</div>
      </div>
      {status ? <div className="sidebar__group">{status}</div> : null}
      <nav aria-label="Primary">
        {groups.map((group) => (
          <div className="sidebar__group" key={group.label}>
            <div className="sidebar__group-label">{group.label}</div>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  isActive ? 'sidebar__link sidebar__link--active' : 'sidebar__link'
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      {foot ? <div className="sidebar__foot">{foot}</div> : null}
    </aside>
  );
}
