import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { BrandMark } from "../brand/BrandMark";
import { ThemeButton } from "../brand/ThemeButton";
import { useSession } from "../hooks/useSession";
import { BRAND } from "../marketing/copy";
import { Icon } from "../ui/icons";

/** Landing-page sections the header and footer anchor to. */
export const SECTION_LINKS = [
  { id: "features", label: "Features" },
  { id: "how-it-works", label: "How it works" },
  { id: "developers", label: "Developers" },
  { id: "security", label: "Security" },
] as const;

/** Session-aware call to action: sign in / register, or straight back into the right console. */
function HeaderCta({ onNavigate }: { onNavigate?: () => void }) {
  const { tenant, platform } = useSession();
  if (tenant) return <Link className="btn btn-primary" to="/home" onClick={onNavigate}>Open console</Link>;
  if (platform) return <Link className="btn btn-primary" to="/admin/status" onClick={onNavigate}>Open platform console</Link>;
  return <>
    <Link className="btn btn-ghost" to="/login" onClick={onNavigate}>Sign in</Link>
    <Link className="btn btn-primary" to="/register" onClick={onNavigate}>Create account</Link>
  </>;
}

/**
 * `BrowserRouter` does not scroll to `#id` on its own. After every navigation
 * scroll to the hashed section (from /pricing to /#features too), otherwise to
 * the top, and move focus the way the console shells do.
 */
function useScrollAndFocus() {
  const { pathname, hash, key } = useLocation();
  useEffect(() => {
    const id = hash ? decodeURIComponent(hash.slice(1)) : "";
    const frame = window.requestAnimationFrame(() => {
      const target = id ? document.getElementById(id) : null;
      if (target) {
        target.scrollIntoView?.({ block: "start" });
        target.focus?.({ preventScroll: true });
      } else {
        try { window.scrollTo({ top: 0, left: 0, behavior: "instant" }); } catch { /* jsdom */ }
        document.querySelector<HTMLElement>("#main-content")?.focus({ preventScroll: true });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [pathname, hash, key]);
}

/**
 * Public marketing shell for `/` (signed out) and `/pricing`. Separate from
 * `PublicLayout`, which stays the split-screen auth shell. Every style lives in
 * marketing.css under `.mkt`.
 */
export function MarketingLayout({ children }: { children?: ReactNode }) {
  const { tenant, platform } = useSession();
  const signedIn = !!(tenant || platform);
  const { pathname, hash } = useLocation();
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  useScrollAndFocus();

  // Route (or hash) changes close the mobile menu.
  useEffect(() => { setOpen(false); }, [pathname, hash]);
  // Escape closes it and returns focus to the toggle.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); toggleRef.current?.focus(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  const close = () => setOpen(false);

  // Section anchors only exist on the signed-out landing page; `/` sends a
  // signed-in visitor to their console, so they get Pricing alone.
  const sections = signedIn ? [] : SECTION_LINKS;
  const year = new Date().getFullYear();

  return <div className={`mkt${open ? " nav-open" : ""}`}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="mkt-header">
      <div className="mkt-container mkt-header-inner">
        <Link to="/" className="mkt-brand" aria-label="GraphRec home"><BrandMark /><span>GraphRec</span></Link>
        <nav id="mkt-nav" aria-label="Marketing" className={`mkt-nav${open ? " is-open" : ""}`}>
          <ul>
            {sections.map(s => <li key={s.id}><Link to={{ pathname: "/", hash: `#${s.id}` }} onClick={close}>{s.label}</Link></li>)}
            <li><Link to="/docs" onClick={close}>Docs</Link></li>
            <li><Link to="/pricing" aria-current={pathname === "/pricing" ? "page" : undefined} onClick={close}>Pricing</Link></li>
          </ul>
          <div className="mkt-nav-cta"><HeaderCta onNavigate={close} /></div>
        </nav>
        <div className="mkt-actions">
          <ThemeButton compact />
          <div className="mkt-cta-desktop"><HeaderCta /></div>
          <button ref={toggleRef} type="button" className="icon-button nav-toggle mkt-nav-toggle" aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open} aria-controls="mkt-nav" onClick={() => setOpen(!open)}><Icon name={open ? "x" : "menu"} size={20} /></button>
        </div>
      </div>
    </header>
    {open ? <div className="mkt-scrim" aria-hidden="true" onClick={close} /> : null}
    <main id="main-content" tabIndex={-1} className="mkt-main">{children ?? <Outlet />}</main>
    <footer className="mkt-footer">
      <div className="mkt-container">
        <div className="mkt-footer-grid">
          <div className="mkt-footer-brand">
            <Link to="/" className="mkt-brand" aria-label="GraphRec home"><BrandMark /><span>GraphRec</span></Link>
            <p>{BRAND.description}</p>
          </div>
          <nav aria-label="Product" className="mkt-footer-col">
            <h2>Product</h2>
            <ul>
              {sections.filter(s => s.id === "features" || s.id === "how-it-works").map(s => <li key={s.id}><Link to={{ pathname: "/", hash: `#${s.id}` }}>{s.label}</Link></li>)}
              <li><Link to="/pricing">Pricing</Link></li>
            </ul>
          </nav>
          <nav aria-label="Console" className="mkt-footer-col">
            <h2>Console</h2>
            <ul>
              <li><Link to="/login">Sign in</Link></li>
              <li><Link to="/register">Create account</Link></li>
              <li><Link to="/setup">Finish account setup</Link></li>
              <li><Link to="/recover">Reset password</Link></li>
            </ul>
          </nav>
          <nav aria-label="Developers" className="mkt-footer-col">
            <h2>Developers</h2>
            <ul>
              <li><Link to="/docs">Documentation</Link></li>
              <li><Link to="/docs/reference">API Reference</Link></li>
              <li><Link to="/docs/sdk">Python SDK</Link></li>
              <li><Link to="/docs/errors-and-limits#changelog">Changelog</Link></li>
            </ul>
          </nav>
          <nav aria-label="Operators" className="mkt-footer-col">
            <h2>Operators</h2>
            <ul><li><Link to="/admin/login">Platform sign-in</Link></li></ul>
          </nav>
        </div>
        <div className="mkt-footer-base">
          <span>© {year} GraphRec</span>
          <ThemeButton />
        </div>
      </div>
    </footer>
  </div>;
}
