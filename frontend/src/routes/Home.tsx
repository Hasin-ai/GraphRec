import { Link } from 'react-router-dom';
import { useTenantContext } from '../layouts/TenantLayout';
import { tenantNav } from '../layouts/nav';
import type { TenantRole } from '../lib/enums';

/**
 * `/home` — the permitted-services launcher.
 *
 * §7 is emphatic that this is a launcher and **not** an analytics dashboard:
 * no charts, no KPI tiles. It shows the modules this role may enter, which is
 * why an Administrator and a Developer see materially different pages, and it
 * derives that from the same table the sidebar uses so the two cannot disagree.
 *
 * The onboarding checklist §5c describes belongs on this page and is not here
 * yet: it reflects real state (catalogue non-empty, events received, a
 * succeeded job, an active version) and the endpoint that reports that state
 * arrives with the tenant routes in Phase 14.
 */
export function HomeRoute() {
  const { me, tenant } = useTenantContext();
  const groups = tenantNav(me.role as TenantRole).filter((group) => group.label !== 'Workspace');

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">{tenant.tenant_name}</h1>
        <p className="page__lede">
          What your role can reach. Anything not listed here is not yours to open, and the server
          refuses it independently of this page.
        </p>
      </div>

      <div className="stack">
        {groups.map((group) => (
          <section key={group.label}>
            <h2 className="eyebrow">{group.label}</h2>
            <ul className="stack--tight" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {group.items.map((item) => (
                <li key={item.to}>
                  <Link to={item.to}>{item.label}</Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
