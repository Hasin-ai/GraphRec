import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { consumeExplicitSignOut, roleLabel, sessionTenantId } from "../auth/session";
import { useSession } from "../hooks/useSession";
import { useTheme } from "../hooks/useTheme";
import { IdChip } from "../ui/primitives";

interface NavItem { label: string; to: string; scope?: string; end?: boolean }
interface NavGroup { label: string; items: NavItem[] }
const TENANT_NAV: NavGroup[] = [
  { label: "", items: [{ label: "Overview", to: "/home" }] },
  { label: "Data", items: [
    { label: "Products", to: "/products", scope: "catalog:read", end: true },
    { label: "Catalog sync", to: "/products/sync", scope: "catalog:write" },
    { label: "Events", to: "/events/submit", scope: "events:write" },
    { label: "Datasets", to: "/datasets", scope: "training:read" },
  ] },
  { label: "Models", items: [
    { label: "Training", to: "/training", scope: "training:read" },
    { label: "Model Versions", to: "/models", scope: "models:read" },
  ] },
  { label: "Recommendations", items: [
    { label: "Rules", to: "/recommendation-rules", scope: "models:read" },
  ] },
  { label: "Monitoring", items: [
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

function isActive(item: NavItem, pathname: string) {
  if (item.to === "/products") return pathname === "/products" || (pathname.startsWith("/products/") && pathname !== "/products/sync");
  return item.end ? pathname === item.to : pathname === item.to || pathname.startsWith(item.to + "/");
}
function Nav({ groups, can }: { groups: NavGroup[]; can: (scope: string) => boolean }) {
  const { pathname } = useLocation();
  return <nav aria-label="Primary">{groups.map(group => {
    const items = group.items.filter(item => !item.scope || can(item.scope));
    if (!items.length) return null;
    return <div className="nav-group" key={group.label}>
      {group.label ? <div className="nav-label">{group.label}</div> : null}
      <div className="nav-items">{items.map(item => <NavLink key={item.to} to={item.to} end={item.end}
        aria-current={isActive(item, pathname) ? "page" : undefined}
        className={() => `nav-item${isActive(item, pathname) ? " active" : ""}`}>
        {item.label}
      </NavLink>)}</div>
    </div>;
  })}</nav>;
}

/** A readable workspace name derived from the account's email domain ("beauty.example" → "Beauty"). */
function workspaceName(email: string | undefined): string | null {
  const domain = email?.split("@")[1];
  if (!domain) return null;
  const label = domain.split(".")[0].replace(/[-_]+/g, " ");
  return label ? label.replace(/\b\w/g, c => c.toUpperCase()) : null;
}
function Avatar({ email }: { email?: string }) {
  const local = (email ?? "?").split("@")[0].replace(/[^a-z0-9]/gi, "");
  return <span className="avatar" aria-hidden="true">{(local.slice(0, 1) || "?").toUpperCase()}</span>;
}

function Shell({ aside, children, narrow }: { aside?: ReactNode; children: ReactNode; narrow?: boolean }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => {
    setOpen(false);
    document.querySelector<HTMLElement>('#main-content')?.focus({ preventScroll: true });
  }, [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);
  return <div className={`shell${open ? ' nav-open' : ''}`}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    {aside ? <div className="mobile-header"><Link to="/"><BrandMark />GraphRec</Link><button type="button" className="icon-btn nav-toggle" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} aria-controls="console-navigation" onClick={() => setOpen(!open)}>
      {open ? <svg aria-hidden="true" viewBox="0 0 20 20" width="20" height="20"><path d="M5 5l10 10M15 5L5 15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
        : <svg aria-hidden="true" viewBox="0 0 20 20" width="20" height="20"><path d="M3 5.5h14M3 10h14M3 14.5h14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>}
    </button></div> : null}
    {aside}
    {aside && open ? <div className="nav-scrim" aria-hidden="true" onClick={() => setOpen(false)} /> : null}
    <main id="main-content" tabIndex={-1} className={`main${narrow ? " narrow" : ""}`}>{children}</main>
  </div>;
}
function ThemeButton({ compact }: { compact?: boolean }) {
  const [theme, toggle] = useTheme();
  const next = theme === "light" ? "Dark" : "Light";
  return <button type="button" className={`theme-toggle${compact ? " compact" : ""}`} onClick={toggle} aria-label={`Switch to ${next.toLowerCase()} theme`} title={`Switch to ${next.toLowerCase()} theme`}>
    {theme === "light"
      ? <svg aria-hidden="true" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
      : <svg aria-hidden="true" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>}
    {compact ? null : <span>{next}</span>}
  </button>;
}
function BrandMark() {
  return <svg className="brand-mark" aria-hidden="true" viewBox="0 0 32 32" width="26" height="26">
    <rect width="32" height="32" rx="8" fill="var(--color-ink)" />
    <g stroke="var(--color-on-ink)" strokeWidth="1.6" opacity=".55"><path d="M10 11l12 -1M10 11l5 11M22 10l-7 12M22 10l2 9" /></g>
    <circle cx="10" cy="11" r="3" fill="var(--color-on-ink)" /><circle cx="22" cy="10" r="2.4" fill="var(--color-on-ink)" />
    <circle cx="15" cy="22" r="3" fill="var(--color-accent)" /><circle cx="24" cy="19" r="2" fill="var(--color-on-ink)" />
  </svg>;
}
/** Decorative user–item graph for the auth showcase panel. */
function GraphIllustration() {
  const nodes: [number, number, number, boolean][] = [
    [60, 70, 7, false], [170, 40, 5, false], [260, 95, 8, true], [120, 150, 6, false], [215, 185, 5, false],
    [320, 175, 6, false], [70, 235, 5, false], [175, 265, 9, true], [295, 270, 5, false], [345, 60, 4, false],
  ];
  const edges = [[0,1],[0,3],[1,2],[2,3],[2,5],[2,9],[3,4],[3,6],[4,7],[5,8],[6,7],[7,8],[4,5],[1,9]];
  return <svg className="auth-graph" aria-hidden="true" viewBox="0 0 400 310" preserveAspectRatio="xMidYMid meet">
    {edges.map(([a, b], i) => <line key={i} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]} className={nodes[a][3] && nodes[b][3] ? "e hot" : nodes[a][3] || nodes[b][3] ? "e warm" : "e"} />)}
    {nodes.map(([x, y, r, hot], i) => <g key={i}>{hot ? <circle cx={x} cy={y} r={r + 7} className="halo" /> : null}<circle cx={x} cy={y} r={r} className={hot ? "n hot" : "n"} /></g>)}
  </svg>;
}
export function PublicLayout() {
  const { pathname } = useLocation();
  useEffect(() => { document.querySelector<HTMLElement>("#main-content")?.focus({ preventScroll: true }); }, [pathname]);
  return <div className="auth-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className="auth-showcase" aria-label="About GraphRec">
      <Link to="/" className="auth-logo"><BrandMark />GraphRec</Link>
      <div className="auth-pitch">
        <GraphIllustration />
        <h2>Recommendations that learn from every interaction.</h2>
        <p>Sync your catalog, stream events, and serve time-aware graph recommendations from one multi-tenant console.</p>
        <ul>
          <li>Train and version models on your own event history</li>
          <li>Promote, roll back and monitor serving deployments</li>
          <li>Scoped API keys and per-tenant usage quotas</li>
        </ul>
      </div>
      <div className="auth-foot">© {new Date().getFullYear()} GraphRec</div>
    </aside>
    <div className="auth-pane">
      <header className="auth-top">
        <Link to="/" className="auth-logo mobile-only"><BrandMark />GraphRec</Link>
        <ThemeButton />
      </header>
      <main id="main-content" tabIndex={-1} className="auth-main">
        <div className="auth-card"><p className="auth-pitch-mobile">Recommendations that learn from every interaction.</p><Outlet /></div>
      </main>
    </div>
  </div>;
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
    <div className="aside-brand"><Link to="/home" className="name"><BrandMark />GraphRec</Link>
      <div className="workspace-block"><span className="wb-eyebrow">Workspace</span><Link to="/account" className="wb-name">{workspaceName(tenant.email) ?? "Tenant console"}</Link>{tenantId ? <span className="wb-id">Tenant ID <IdChip value={tenantId} length={8} label="Tenant ID" /></span> : null}</div></div>
    <Nav groups={TENANT_NAV} can={can} />
    <div className="aside-foot">
      <Link to="/account" className="who-card" title={tenant.email}><Avatar email={tenant.email} /><span className="who-text"><span className="who">{(tenant.email || "Signed-in user").split("@")[0]}</span><span className="role">{roleLabel(tenant.role)}</span></span></Link>
      <div className="links"><Link to="/account" className="foot-link">Account</Link><button type="button" className="foot-link" onClick={signOutTenant}>Sign out</button><ThemeButton compact /></div>
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
    <div className="aside-brand"><Link to="/admin/status" className="name"><BrandMark />GraphRec</Link><div className="workspace-block"><span className="wb-eyebrow">Console</span><span className="wb-name">Platform operator</span></div></div>
    <Nav groups={PLATFORM_NAV} can={() => true} />
    <div className="aside-foot"><div className="who-card"><span className="avatar" aria-hidden="true">P</span><span className="who-text"><span className="who">Platform operator</span><span className="role">Administrator token</span></span></div><div className="links"><button type="button" className="foot-link" onClick={signOutPlatform}>Sign out</button><ThemeButton compact /></div></div>
  </aside>}><Outlet /></Shell>;
}
export function ErrorLayout() {
  const { tenant, platform } = useSession();
  return tenant ? <TenantLayout /> : platform ? <PlatformLayout /> : <PublicLayout />;
}
