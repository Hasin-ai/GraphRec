import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { consumeExplicitSignOut, hasOperatorRole, roleLabel, sessionTenantId, type OperatorRole } from "../auth/session";
import { useMeta } from "../hooks/useMeta";
import { useSession } from "../hooks/useSession";
import { useTheme, type ThemeMode } from "../hooks/useTheme";
import { useToast } from "../hooks/useToast";
import { BrandMark, GraphIllustration } from "../brand/BrandMark";
import { ThemeButton } from "../brand/ThemeButton";
import { BRAND } from "../marketing/copy";
import { Icon, type IconName } from "../ui/icons";
import { menuKeys, usePopover } from "../ui/kit";

interface NavItem { label: string; to: string; icon: IconName; scope?: string; end?: boolean }
interface NavGroup { id: string; label: string; items: NavItem[] }
/** Information architecture. Every route predates this pass except /playground. */
const TENANT_NAV: NavGroup[] = [
  { id: "top", label: "", items: [{ label: "Overview", to: "/home", icon: "home" }] },
  { id: "data", label: "Data", items: [
    { label: "Products", to: "/products", icon: "box", scope: "catalog:read", end: true },
    { label: "Catalog sync", to: "/products/sync", icon: "refresh-cw", scope: "catalog:write" },
    { label: "Events", to: "/events/submit", icon: "activity", scope: "events:write" },
    { label: "Datasets", to: "/datasets", icon: "database", scope: "training:read" },
  ] },
  { id: "models", label: "Models", items: [
    { label: "Training", to: "/training", icon: "cpu", scope: "training:read" },
    { label: "Model Versions", to: "/models", icon: "layers", scope: "models:read" },
  ] },
  { id: "recs", label: "Recommendations", items: [
    { label: "Rules", to: "/recommendation-rules", icon: "sliders", scope: "models:read" },
    { label: "Playground", to: "/playground", icon: "play", scope: "recommendations:read" },
  ] },
  { id: "monitoring", label: "Monitoring", items: [
    { label: "Service Status", to: "/service-status", icon: "server", scope: "deployments:read" },
    { label: "Usage & Quotas", to: "/usage", icon: "gauge", scope: "usage:read" },
  ] },
  { id: "developer", label: "Developer", items: [
    { label: "API Credentials", to: "/credentials", icon: "key", scope: "keys:write" },
    { label: "Integration", to: "/integration", icon: "plug" },
  ] },
  { id: "admin", label: "Admin", items: [
    { label: "Team members", to: "/users", icon: "users", scope: "users:write" },
    { label: "Audit trail", to: "/audit", icon: "activity", scope: "audit:read" },
  ] },
];
/** D-04: platform items name the operator roles that may open them ("a|b" = any of). */
const PLATFORM_NAV: NavGroup[] = [{ id: "platform", label: "Platform", items: [
  { label: "Platform Status", to: "/admin/status", icon: "server" },
  { label: "Tenants", to: "/admin/tenants", icon: "users", scope: "platform|plan_management|monitoring|audit" },
  { label: "Plans & Quotas", to: "/admin/plans", icon: "gauge", scope: "plan_management|platform|monitoring" },
  { label: "Usage", to: "/admin/usage", icon: "gauge", scope: "monitoring|plan_management" },
  { label: "Failures & Audit", to: "/admin/audit", icon: "activity", scope: "audit|monitoring" },
  { label: "Operators", to: "/admin/operators", icon: "users", scope: "operator_admin" },
] }];

function isActive(item: NavItem, pathname: string) {
  if (item.to === "/products") return pathname === "/products" || (pathname.startsWith("/products/") && pathname !== "/products/sync");
  return item.end ? pathname === item.to : pathname === item.to || pathname.startsWith(item.to + "/");
}

/* ── persisted UI prefs (per browser) ── */
function readPref<T>(key: string, fallback: T): T {
  try { const raw = window.localStorage.getItem(key); return raw === null ? fallback : (JSON.parse(raw) as T); } catch { return fallback; }
}
function usePref<T>(key: string, fallback: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => readPref(key, fallback));
  const set = useCallback((v: T) => { setValue(v); try { window.localStorage.setItem(key, JSON.stringify(v)); } catch { /* ignore */ } }, [key]);
  return [value, set];
}

function Nav({ groups, can, collapsed }: { groups: NavGroup[]; can: (scope: string) => boolean; collapsed: boolean }) {
  const { pathname } = useLocation();
  const [closed, setClosed] = usePref<string[]>("graphrec.nav.closed", []);
  const scroller = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ top: false, bottom: false });
  const measure = useCallback(() => {
    const el = scroller.current; if (!el) return;
    setEdges({ top: el.scrollTop > 2, bottom: el.scrollTop + el.clientHeight < el.scrollHeight - 2 });
  }, []);
  useEffect(() => {
    measure();
    const el = scroller.current; if (!el) return;
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [measure, closed, collapsed]);
  // Keep the current page visible when the nav is taller than the viewport.
  useEffect(() => { scroller.current?.querySelector<HTMLElement>('[aria-current="page"]')?.scrollIntoView?.({ block: "nearest" }); }, [pathname]);

  return <div ref={scroller} className={`sb-nav${edges.top ? " at-top-shadow" : ""}${edges.bottom ? " at-bottom-shadow" : ""}`} onScroll={measure}>
    <nav aria-label="Primary">{groups.map(group => {
      const items = group.items.filter(item => !item.scope || can(item.scope));
      if (!items.length) return null;
      const hasActive = items.some(item => isActive(item, pathname));
      const isClosed = !collapsed && group.label !== "" && closed.includes(group.id) && !hasActive;
      const listId = `nav-group-${group.id}`;
      return <div className={`nav-group${isClosed ? " is-closed" : ""}`} key={group.id}>
        {group.label ? (collapsed ? <div className="nav-sep" role="separator" aria-label={group.label} />
          : <button type="button" className="nav-heading" aria-expanded={!isClosed} aria-controls={listId}
              onClick={() => setClosed(isClosed ? closed.filter(id => id !== group.id) : [...closed, group.id])}>
              <span>{group.label}</span><Icon name="chevron-down" size={14} className="nav-chev" />
            </button>) : null}
        <ul className="nav-items" id={listId} hidden={isClosed}>{items.map(item => {
          const active = isActive(item, pathname);
          return <li key={item.to}><NavLink to={item.to} end={item.end} aria-current={active ? "page" : undefined}
            aria-label={collapsed ? item.label : undefined} data-tip={collapsed ? item.label : undefined}
            className={() => `nav-item${active ? " active" : ""}`}>
            <Icon name={item.icon} size={17} className="nav-icon" /><span className="nav-text">{item.label}</span>
          </NavLink></li>;
        })}</ul>
      </div>;
    })}</nav>
  </div>;
}

/** A friendly display name: "dana.lee@x" → "Dana Lee"; machine-like handles ("owner-39f889") → "Workspace owner". */
function displayName(email: string | undefined, role?: string): string {
  const local = (email ?? "").split("@")[0];
  if (!local) return "Signed-in user";
  if (/\d{3,}|^[a-f0-9-]{8,}$/i.test(local)) return role === "tenant_administrator" ? "Workspace owner" : "Team member";
  return local.split(/[._-]+/).filter(Boolean).map(w => w[0].toUpperCase() + w.slice(1)).join(" ");
}
function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

function WorkspaceSwitcher({ name, tenantId, home, collapsed, caption }: { name: string; tenantId: string | null; home: string; collapsed: boolean; caption: string }) {
  const pop = usePopover<HTMLDivElement>();
  const { copy } = useToast();
  useEffect(() => { if (pop.open) pop.ref.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus(); }, [pop.open, pop.ref]);
  return <div className="ws">
    <button ref={pop.triggerRef} type="button" className="ws-trigger" aria-haspopup="menu" aria-expanded={pop.open} onClick={pop.toggle}
      aria-label={`Workspace: ${name}`} data-tip={collapsed ? name : undefined}>
      <span className="ws-avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>
      <span className="ws-text"><span className="ws-name">{name}</span><span className="ws-caption">{caption}</span></span>
      <Icon name="chevrons-up-down" size={14} className="ws-chev" />
    </button>
    {pop.open ? <div ref={pop.ref} className="menu ws-menu" role="menu" aria-label="Workspace" onKeyDown={menuKeys}>
      {/* One account belongs to exactly one workspace (tenant); there is nothing to switch to. */}
      <Link role="menuitem" className="menu-item" to={home} onClick={() => pop.setOpen(false)}>
        <span className="ws-avatar sm" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>{name}
      </Link>
      {tenantId ? <>
        <div className="menu-sep" role="separator" />
        <div className="menu-meta"><span>Tenant ID</span><code title={tenantId}>{tenantId}</code></div>
        <button type="button" role="menuitem" className="menu-item" onClick={() => { copy(tenantId); pop.setOpen(false); }}><Icon name="copy" size={15} />Copy tenant ID</button>
      </> : null}
    </div> : null}
  </div>;
}

const THEME_OPTIONS: { mode: ThemeMode; label: string; icon: IconName }[] = [
  { mode: "light", label: "Light", icon: "sun" }, { mode: "dark", label: "Dark", icon: "moon" }, { mode: "system", label: "System", icon: "monitor" },
];
function UserMenu({ name, detail, role, collapsed, onSignOut, accountTo, plansTo }: { name: string; detail?: string; role: string; collapsed: boolean; onSignOut: () => void; accountTo?: string; plansTo?: string }) {
  const pop = usePopover<HTMLDivElement>();
  const [, , mode, setMode] = useTheme();
  useEffect(() => { if (pop.open) pop.ref.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus(); }, [pop.open, pop.ref]);
  return <div className="um">
    {pop.open ? <div ref={pop.ref} className="menu um-menu" role="menu" aria-label="Account" onKeyDown={menuKeys}>
      <div className="menu-head"><strong>{name}</strong>{detail ? <span title={detail}>{detail}</span> : null}</div>
      <div className="menu-sep" role="separator" />
      {accountTo ? <Link role="menuitem" className="menu-item" to={accountTo} onClick={() => pop.setOpen(false)}><Icon name="user" size={15} />Account</Link> : null}
      {plansTo ? <Link role="menuitem" className="menu-item muted" to={plansTo} onClick={() => pop.setOpen(false)}><Icon name="gauge" size={15} />Plans &amp; limits</Link> : null}
      <div className="menu-label">Theme</div>
      <div className="seg" role="group" aria-label="Theme">
        {THEME_OPTIONS.map(o => <button key={o.mode} type="button" role="menuitemradio" aria-checked={mode === o.mode} className={`seg-btn${mode === o.mode ? " on" : ""}`} onClick={() => setMode(o.mode)}>
          <Icon name={o.icon} size={14} />{o.label}</button>)}
      </div>
      <div className="menu-sep" role="separator" />
      <button type="button" role="menuitem" className="menu-item" onClick={() => { pop.setOpen(false); onSignOut(); }}><Icon name="log-out" size={15} />Sign out</button>
    </div> : null}
    <button ref={pop.triggerRef} type="button" className="um-trigger" aria-haspopup="menu" aria-expanded={pop.open} onClick={pop.toggle}
      aria-label={`Account menu for ${name}`} data-tip={collapsed ? name : undefined}>
      <span className="avatar" aria-hidden="true">{initials(name)}</span>
      <span className="um-text"><span className="um-name">{name}</span><span className="role-badge">{role}</span></span>
      <Icon name="chevrons-up-down" size={14} className="ws-chev" />
    </button>
  </div>;
}

/** One product version for API, console and SDK (`GET /v1/meta`); hidden until known. */
function ProductVersion({ collapsed }: { collapsed: boolean }) {
  const meta = useMeta();
  if (!meta || collapsed) return null;
  return <div className="sb-version" data-testid="product-version">GraphRec v{meta.version}{meta.environment === "development" ? " · development" : ""}</div>;
}

function Sidebar({ home, groups, can, header, footer, collapsed, onCollapse, onClose }: {
  home: string; groups: NavGroup[]; can: (s: string) => boolean; header: (collapsed: boolean) => ReactNode; footer: (collapsed: boolean) => ReactNode;
  collapsed: boolean; onCollapse: () => void; onClose: () => void;
}) {
  return <aside id="console-navigation" className="sidebar" aria-label="Sidebar">
    <div className="sb-head">
      <div className="sb-brand">
        <Link to={home} className="sb-logo" aria-label="GraphRec home"><BrandMark /><span className="sb-logo-text">GraphRec</span></Link>
        <button type="button" className="icon-button sb-collapse" onClick={onCollapse} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} data-tip={collapsed ? "Expand sidebar" : undefined}><Icon name="panel-left" /></button>
        <button type="button" className="icon-button sb-close" onClick={onClose} aria-label="Close navigation"><Icon name="x" /></button>
      </div>
      {header(collapsed)}
    </div>
    <Nav groups={groups} can={can} collapsed={collapsed} />
    <div className="sb-foot">{footer(collapsed)}<ProductVersion collapsed={collapsed} /></div>
  </aside>;
}

function Shell({ home, sidebar, children }: { home: string; sidebar: (state: { collapsed: boolean; toggleCollapsed: () => void; closeDrawer: () => void }) => ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const midWidth = typeof window !== "undefined" && window.matchMedia?.("(max-width: 1279px)").matches;
  const [collapsed, setCollapsed] = usePref<boolean>("graphrec.sidebar.collapsed", !!midWidth);
  const [drawer, setDrawer] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.("(max-width: 1023px)").matches);
  useEffect(() => {
    const mq = window.matchMedia?.("(max-width: 1023px)");
    if (!mq) return;
    const on = () => setDrawer(mq.matches);
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  const railCollapsed = collapsed && !drawer;
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
  return <div className={`app-shell${open ? ' nav-open' : ''}${railCollapsed ? ' sb-collapsed' : ''}`}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="topbar">
      <button type="button" className="icon-button" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} aria-controls="console-navigation" onClick={() => setOpen(!open)}><Icon name={open ? "x" : "menu"} size={18} /></button>
      <Link to={home} className="sb-logo"><BrandMark />GraphRec</Link>
    </header>
    {sidebar({ collapsed: railCollapsed, toggleCollapsed: () => setCollapsed(!collapsed), closeDrawer: () => setOpen(false) })}
    {open ? <div className="nav-scrim" aria-hidden="true" onClick={() => setOpen(false)} /> : null}
    <main id="main-content" tabIndex={-1} className="main"><div className="content">{children}</div></main>
  </div>;
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
        <h2>{BRAND.tagline}</h2>
        <p>{BRAND.lede}</p>
        <ul>{BRAND.pillars.map(pillar => <li key={pillar}>{pillar}</li>)}</ul>
      </div>
      <div className="auth-foot">© {new Date().getFullYear()} GraphRec<span aria-hidden="true"> · </span><Link to="/pricing">Plans &amp; limits</Link></div>
    </aside>
    <div className="auth-pane">
      <header className="auth-top">
        <Link to="/" className="auth-logo mobile-only"><BrandMark />GraphRec</Link>
        <Link to="/" className="auth-back" aria-label="Back to GraphRec home"><span aria-hidden="true">←</span><span className="auth-back-long">Back to GraphRec</span><span className="auth-back-short">Home</span></Link>
        <ThemeButton />
      </header>
      <main id="main-content" tabIndex={-1} className="auth-main">
        <div className="auth-card"><p className="auth-pitch-mobile">{BRAND.tagline}</p><Outlet /></div>
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
/** D-13: a member of a suspended workspace holds only this scope and sees only its status. */
export function isRestrictedSession(scopes: string[]): boolean {
  return scopes.length === 1 && scopes[0] === "account:status";
}

export function TenantLayout() {
  const { tenant, can, signOutTenant } = useSession();
  const location = useLocation();
  if (!tenant) return <Navigate to="/login" replace />;
  if (isRestrictedSession(tenant.scopes)) {
    if (location.pathname !== "/account/tenant-status") return <Navigate to="/account/tenant-status" replace />;
    return <main id="main-content" className="state-gate"><Outlet /></main>;
  }
  const tenantId = sessionTenantId(tenant);
  const name = displayName(tenant.email, tenant.role);
  const role = roleLabel(tenant.role).replace(/^tenant /, "");
  return <Shell key={tenant.accessToken} home="/home" sidebar={({ collapsed, toggleCollapsed, closeDrawer }) => <Sidebar home="/home" groups={TENANT_NAV} can={can}
    collapsed={collapsed} onCollapse={toggleCollapsed} onClose={closeDrawer}
    header={c => <WorkspaceSwitcher name={tenant.tenantName ?? "Your workspace"} tenantId={tenantId} home="/home" collapsed={c} caption="Tenant workspace" />}
    footer={c => <UserMenu name={name} detail={tenant.email} role={role[0].toUpperCase() + role.slice(1)} collapsed={c} onSignOut={signOutTenant} accountTo="/account" plansTo="/pricing" />} />}>
    <Outlet />
  </Shell>;
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
  return <Shell key={platform.token} home="/admin/status" sidebar={({ collapsed, toggleCollapsed, closeDrawer }) => <Sidebar home="/admin/status" groups={PLATFORM_NAV} can={scope => hasOperatorRole(platform, ...(scope.split("|") as OperatorRole[]))}
    collapsed={collapsed} onCollapse={toggleCollapsed} onClose={closeDrawer}
    header={c => <WorkspaceSwitcher name="Platform" tenantId={null} home="/admin/status" collapsed={c} caption="Operator console" />}
    footer={c => <UserMenu name={platform.displayName ?? "Platform operator"} detail={platform.email ?? "Development bootstrap token"} role={platform.credential === "operator" ? "Operator" : "Bootstrap"} collapsed={c} onSignOut={signOutPlatform} />} />}>
    <Outlet />
  </Shell>;
}
export function ErrorLayout() {
  const { tenant, platform } = useSession();
  return tenant ? <TenantLayout /> : platform ? <PlatformLayout /> : <PublicLayout />;
}
