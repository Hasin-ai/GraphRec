import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { consumeExplicitSignOut, roleLabel, sessionTenantId } from "../auth/session";
import { useSession } from "../hooks/useSession";
import { useTheme } from "../hooks/useTheme";

interface NavItem { label: string; to: string; scope?: string; end?: boolean }
interface NavGroup { label: string; items: NavItem[] }
const TENANT_NAV: NavGroup[] = [
  { label: "", items: [{ label: "Overview", to: "/home" }] },
  { label: "Data", items: [
    { label: "Products", to: "/products", scope: "catalog:read", end: true },
    { label: "Synchronize Catalog", to: "/products/sync", scope: "catalog:write" },
    { label: "Submit Events", to: "/events/submit", scope: "events:write" },
    { label: "Datasets", to: "/datasets", scope: "training:read" },
  ] },
  { label: "Models", items: [
    { label: "Training", to: "/training", scope: "training:read" },
    { label: "Model Versions", to: "/models", scope: "models:read" },
    { label: "Recommendation Rules", to: "/recommendation-rules", scope: "models:read" },
  ] },
  { label: "Operations", items: [
    { label: "Service Status", to: "/service-status", scope: "deployments:read" },
    { label: "Usage & Quotas", to: "/usage", scope: "usage:read" },
  ] },
  { label: "Developer", items: [
    { label: "API Credentials", to: "/credentials", scope: "keys:write" },
    { label: "Integration", to: "/integration" },
  ] },
  { label: "Administration", items: [{ label: "Team members", to: "/users", scope: "users:write" }] },
];
const PLATFORM_NAV: NavGroup[] = [{ label: "Platform", items: [
  { label: "Platform Status", to: "/admin/status" }, { label: "Tenants", to: "/admin/tenants" },
  { label: "Plans & Quotas", to: "/admin/plans" }, { label: "Failures & Audit", to: "/admin/audit" },
] }];

function Nav({ groups, can }: { groups: NavGroup[]; can: (scope: string) => boolean }) {
  const { pathname } = useLocation();
  return <nav aria-label="Primary">{groups.map(group => {
    const items = group.items.filter(item => !item.scope || can(item.scope));
    return items.length ? <div className="nav-group" key={group.label}>
      {group.label ? <div className="nav-label">{group.label}</div> : null}
      {items.map(item => <NavLink key={item.to} to={item.to} end={item.end}
        aria-current={item.to === '/products' && pathname.startsWith('/products/') && pathname !== '/products/sync' ? 'page' : undefined}
        className={({ isActive }) => `nav-item${isActive || (item.to === '/products' && pathname.startsWith('/products/') && pathname !== '/products/sync') ? ' active' : ''}`}>
        {item.label}
      </NavLink>)}
    </div> : null;
  })}</nav>;
}

function Shell({ aside, children, narrow }: { aside?: ReactNode; children: ReactNode; narrow?: boolean }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => {
    setOpen(false);
    document.querySelector<HTMLElement>('#main-content')?.focus({ preventScroll: true });
  }, [pathname]);
  return <div className={`shell${open ? ' nav-open' : ''}`}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    {aside ? <div className="mobile-header"><Link to="/">GraphRec</Link><button type="button" className="btn btn-secondary" aria-expanded={open} aria-controls="console-navigation" onClick={() => setOpen(!open)}>{open ? 'Close navigation' : 'Open navigation'}</button></div> : null}
    {aside}
    <main id="main-content" tabIndex={-1} className={`main${narrow ? " narrow" : ""}`}>{children}</main>
  </div>;
}
function ThemeButton() {
  const [theme, toggle] = useTheme();
  return <button type="button" className="btn btn-ghost" onClick={toggle} aria-label="Toggle colour theme">{theme === "light" ? "Dark" : "Light"}</button>;
}
export function PublicLayout() {
  return <Shell narrow><div className="public-brand"><Link to="/">GraphRec</Link><ThemeButton /></div><Outlet /></Shell>;
}
export function RequireTenant() {
  const { tenant } = useSession();
  const location = useLocation();
  if (!tenant) {
    // Expired sessions keep the return path; an explicit sign-out clears it so
    // the next person to sign in on this tab starts at their own Overview.
    if (consumeExplicitSignOut()) return <Navigate to="/login" replace />;
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return <Outlet />;
}
export function RequireScope({ scope, children }: { scope: string; children: ReactNode }) {
  const { can } = useSession();
  if (!can(scope)) return <Navigate to="/403" replace />;
  return <>{children}</>;
}
export function TenantLayout() {
  const { tenant, can, signOutTenant } = useSession();
  if (!tenant) return <Navigate to="/login" replace />;
  const tenantId = sessionTenantId(tenant);
  return <Shell key={tenant.accessToken} aside={<aside id="console-navigation" className="aside">
    <div className="aside-brand"><Link to="/home" className="name">GraphRec</Link><Link to="/account" className="scope" title={tenantId ?? undefined}>{tenantId ? `Tenant ${tenantId.slice(0, 8)}` : 'Tenant console'}</Link></div>
    <Nav groups={TENANT_NAV} can={can} />
    <div className="aside-foot"><Link to="/account" className="who">{tenant.email || "Signed-in user"}</Link><div className="role">{roleLabel(tenant.role)}</div>
      <div className="links"><Link to="/account">Account</Link><button type="button" className="btn btn-ghost" onClick={signOutTenant}>Sign out</button><ThemeButton /></div>
    </div>
  </aside>}><Outlet /></Shell>;
}
export function RequirePlatform() {
  const { platform } = useSession();
  const location = useLocation();
  if (!platform) return <Navigate to="/admin/login" replace state={{ from: location.pathname + location.search }} />;
  return <Outlet />;
}
export function PlatformLayout() {
  const { platform, signOutPlatform } = useSession();
  if (!platform) return <Navigate to="/admin/login" replace />;
  return <Shell key={platform.token} aside={<aside id="console-navigation" className="aside">
    <div className="aside-brand"><Link to="/admin/status" className="name">GraphRec</Link><div className="scope">Platform console</div></div>
    <Nav groups={PLATFORM_NAV} can={() => true} />
    <div className="aside-foot"><div className="who">Platform operator</div><div className="role">Administrator token</div><div className="links"><button type="button" className="btn btn-ghost" onClick={signOutPlatform}>Sign out</button><ThemeButton /></div></div>
  </aside>}><Outlet /></Shell>;
}
export function ErrorLayout() {
  const { tenant, platform } = useSession();
  return tenant ? <TenantLayout /> : platform ? <PlatformLayout /> : <PublicLayout />;
}
