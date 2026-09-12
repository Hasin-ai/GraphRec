import type { ReactNode } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { serving, models } from "../api";
import { roleLabel } from "../auth/session";
import { useResource } from "../hooks/useResource";
import { useSession } from "../hooks/useSession";
import { useTheme } from "../hooks/useTheme";
import { Badge, Tag } from "../ui/primitives";

interface NavItem {
  label: string;
  to: string;
  scope?: string;
  end?: boolean;
}

/**
 * Navigation is derived from the scopes the login actually returned, not from
 * a role table: the API decides what a credential may do (gate 3), the console
 * only avoids offering what would be refused.
 */
const TENANT_NAV: NavItem[][] = [
  [
    { label: "Home", to: "/home" },
    { label: "API Credentials", to: "/credentials", scope: "keys:write" },
    { label: "Integration", to: "/integration" },
  ],
  [
    { label: "Products", to: "/products", scope: "catalog:read", end: true },
    { label: "Synchronize Catalog", to: "/products/sync", scope: "catalog:write" },
    { label: "Submit Events", to: "/events/submit", scope: "events:write" },
    { label: "Datasets", to: "/datasets", scope: "training:read" },
  ],
  [
    { label: "Training", to: "/training", scope: "training:read" },
    { label: "Model Versions", to: "/models", scope: "models:read" },
  ],
  [
    { label: "Usage & Quotas", to: "/usage", scope: "usage:read" },
    { label: "Service Status", to: "/service-status", scope: "deployments:read" },
  ],
];

const PLATFORM_NAV: NavItem[][] = [
  [
    { label: "Platform Status", to: "/admin/status" },
    { label: "Tenants", to: "/admin/tenants" },
    { label: "Plans & Quotas", to: "/admin/plans" },
    { label: "Failures & Audit", to: "/admin/audit" },
  ],
];

function Nav({ groups, can }: { groups: NavItem[][]; can: (scope: string) => boolean }) {
  return (
    <nav aria-label="Primary">
      {groups.map((group, i) => {
        const items = group.filter((n) => !n.scope || can(n.scope));
        if (!items.length) return null;
        return (
          <div className="nav-group" key={i}>
            {items.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
                <span>{n.label}</span>
              </NavLink>
            ))}
          </div>
        );
      })}
    </nav>
  );
}

function ServiceBadges() {
  // Re-read on every navigation so an activation elsewhere is reflected in the rail.
  const { pathname } = useLocation();
  const deployment = useResource(() => serving.deployment(), [pathname]);
  const versions = useResource(() => models.list(), [pathname]);
  const active = versions.data?.items?.find((v) => v.status === "active");
  return (
    <div className="aside-badges">
      <div>
        <span className="label-caps">Active model</span>
        <Tag mono>{versions.data ? (active ? active.version_tag : "none") : "…"}</Tag>
      </div>
      <div>
        <span className="label-caps">Serving</span>
        {deployment.data ? <Badge group="deploy" value={deployment.data.status} /> : <Tag mono>{"…"}</Tag>}
      </div>
    </div>
  );
}

function Shell({ aside, children, narrow }: { aside?: ReactNode; children: ReactNode; narrow?: boolean }) {
  return (
    <div className="shell">
      {aside}
      <main className={`main${narrow ? " narrow" : ""}`}>{children}</main>
    </div>
  );
}

function ThemeButton() {
  const [theme, toggle] = useTheme();
  return (
    <button type="button" className="btn btn-ghost" onClick={toggle} aria-label="Toggle colour theme">
      {theme === "light" ? "Dark" : "Light"}
    </button>
  );
}

/** Public layout: brand only, no navigation, centred narrow column. */
export function PublicLayout() {
  return (
    <Shell narrow>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 28 }}>
        <Link to="/" style={{ fontFamily: "var(--font-heading)", fontWeight: 800, fontSize: 19, letterSpacing: "-.02em", color: "inherit" }}>
          GraphRec
        </Link>
        <ThemeButton />
      </div>
      <Outlet />
    </Shell>
  );
}

/** Gate 1: no tenant session sends the visitor to sign-in, remembering where they were going. */
export function RequireTenant() {
  const { tenant } = useSession();
  const location = useLocation();
  if (!tenant) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

/** Gate 3: a route needs a scope the credential does not carry. Terminal, no retry. */
export function RequireScope({ scope, children }: { scope: string; children: ReactNode }) {
  const { can } = useSession();
  if (!can(scope)) return <Navigate to="/403" replace />;
  return <>{children}</>;
}

export function TenantLayout() {
  const { tenant, can, signOutTenant } = useSession();
  if (!tenant) return <Navigate to="/login" replace />;
  const admin = tenant.role === "tenant_administrator";
  return (
    <Shell
      aside={
        <aside className="aside">
          <div className="aside-brand">
            <div className="name">GraphRec</div>
            <div className="scope">{tenant.email}</div>
          </div>
          {admin && can("deployments:read") && can("models:read") ? <ServiceBadges /> : null}
          <Nav groups={TENANT_NAV} can={can} />
          <div className="aside-foot">
            <div className="who">{tenant.email}</div>
            <div className="role">{roleLabel(tenant.role)}</div>
            <div className="links">
              <Link to="/account">Account</Link>
              <button type="button" className="btn btn-ghost" onClick={signOutTenant}>
                Sign out
              </button>
              <ThemeButton />
            </div>
          </div>
        </aside>
      }
    >
      <Outlet />
    </Shell>
  );
}

export function RequirePlatform() {
  const { platform } = useSession();
  const location = useLocation();
  if (!platform) return <Navigate to="/admin/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

export function PlatformLayout() {
  const { platform, signOutPlatform } = useSession();
  if (!platform) return <Navigate to="/admin/login" replace />;
  return (
    <Shell
      aside={
        <aside className="aside">
          <div className="aside-brand">
            <div className="name">GraphRec</div>
            <div className="scope">Platform scope</div>
          </div>
          <Nav groups={PLATFORM_NAV} can={() => true} />
          <div className="aside-foot">
            <div className="who">Platform operator</div>
            <div className="role">shared administrator token</div>
            <div className="links">
              <button type="button" className="btn btn-ghost" onClick={signOutPlatform}>
                Sign out
              </button>
              <ThemeButton />
            </div>
          </div>
        </aside>
      }
    >
      <Outlet />
    </Shell>
  );
}

/** Error pages render inside whichever layout the visitor has a session for. */
export function ErrorLayout() {
  const { tenant, platform } = useSession();
  if (tenant) return <TenantLayout />;
  if (platform) return <PlatformLayout />;
  return <PublicLayout />;
}
