import { useState, useEffect, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { BrandMark } from "../brand/BrandMark";
import { ThemeButton } from "../brand/ThemeButton";
import { useSession } from "../hooks/useSession";
import { Icon } from "../ui/icons";
import { DocsSearchModal } from "./DocsSearch";
import { DOCS_GROUPS } from "./docsData";

export interface TocItem {
  id: string;
  label: string;
  level?: number;
}

export function DocsLayout({ children }: { children?: ReactNode }) {
  const { tenant, platform } = useSession();
  const { pathname, hash } = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [tocItems, setTocItems] = useState<TocItem[]>([]);
  const [activeHeading, setActiveHeading] = useState<string>("");

  // Close mobile drawer on navigation
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [pathname, hash]);

  // Read page headings for sticky TOC
  useEffect(() => {
    const timer = setTimeout(() => {
      const headings = Array.from(document.querySelectorAll<HTMLElement>("main h2, main h3"));
      const items: TocItem[] = headings
        .filter((h) => h.id)
        .map((h) => ({
          id: h.id,
          label: h.innerText.replace(/^#\s*/, ""),
          level: h.tagName === "H3" ? 3 : 2,
        }));
      setTocItems(items);
    }, 150);
    return () => clearTimeout(timer);
  }, [pathname]);

  // Track active heading on scroll
  useEffect(() => {
    const handleScroll = () => {
      const headings = Array.from(document.querySelectorAll<HTMLElement>("main h2, main h3")).filter((h) => h.id);
      let current = "";
      for (const h of headings) {
        const top = h.getBoundingClientRect().top;
        if (top <= 120) {
          current = h.id;
        }
      }
      setActiveHeading(current);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, [pathname]);

  // Global search shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      }
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div className={`docs-root ${mobileMenuOpen ? "mobile-open" : ""}`}>
      {/* Top Navbar */}
      <header className="docs-topbar">
        <div className="docs-topbar-left">
          <Link to="/" className="docs-brand" aria-label="GraphRec home">
            <BrandMark />
            <span className="docs-brand-name">GraphRec</span>
            <span className="docs-pill">Docs</span>
          </Link>

          <button
            type="button"
            className="docs-search-trigger"
            onClick={() => setSearchOpen(true)}
            aria-label="Search documentation"
          >
            <Icon name="search" size={14} />
            <span>Search docs...</span>
            <kbd className="docs-kbd">⌘K</kbd>
          </button>
        </div>

        <div className="docs-topbar-right">
          <nav className="docs-topbar-nav" aria-label="Documentation topbar">
            <NavLink to="/docs" end className={({ isActive }) => (isActive ? "active" : "")}>
              Getting Started
            </NavLink>
            <NavLink to="/docs/reference" className={({ isActive }) => (isActive ? "active" : "")}>
              API Reference
            </NavLink>
            <NavLink to="/docs/sdk" className={({ isActive }) => (isActive ? "active" : "")}>
              Python SDK
            </NavLink>
            <NavLink to="/pricing">Pricing</NavLink>
          </nav>

          <div className="docs-topbar-actions">
            <ThemeButton compact />
            {tenant ? (
              <Link to="/home" className="btn btn-primary btn-sm">
                Open Console
              </Link>
            ) : platform ? (
              <Link to="/admin/status" className="btn btn-primary btn-sm">
                Platform Console
              </Link>
            ) : (
              <Link to="/login" className="btn btn-secondary btn-sm">
                Sign in
              </Link>
            )}

            <button
              type="button"
              className="docs-mobile-toggle"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label={mobileMenuOpen ? "Close menu" : "Open menu"}
              aria-expanded={mobileMenuOpen}
            >
              <Icon name={mobileMenuOpen ? "x" : "menu"} size={20} />
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <div className="docs-body">
        {/* Left Sidebar */}
        <aside className="docs-sidebar">
          <div className="docs-sidebar-inner">
            <div className="docs-nav-group">
              <div className="docs-nav-heading">Overview</div>
              <ul className="docs-nav-list">
                <li>
                  <NavLink to="/docs" end className={({ isActive }) => (isActive ? "active" : "")}>
                    Getting Started
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/authentication" className={({ isActive }) => (isActive ? "active" : "")}>
                    Authentication & Tenancy
                  </NavLink>
                </li>
              </ul>
            </div>

            <div className="docs-nav-group">
              <div className="docs-nav-heading">API Reference</div>
              <ul className="docs-nav-list">
                <li>
                  <NavLink to="/docs/reference" end className={({ isActive }) => (isActive ? "active" : "")}>
                    All Endpoints Overview
                  </NavLink>
                </li>
                {DOCS_GROUPS.map((g) => (
                  <li key={g.id}>
                    <NavLink to={`/docs/reference#${g.id}`} className={() => (hash === `#${g.id}` ? "active" : "")}>
                      {g.title}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>

            <div className="docs-nav-group">
              <div className="docs-nav-heading">Python SDK</div>
              <ul className="docs-nav-list">
                <li>
                  <NavLink to="/docs/sdk" end className={({ isActive }) => (isActive ? "active" : "")}>
                    SDK Overview & Install
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/sdk#storefront" className={() => (hash === "#storefront" ? "active" : "")}>
                    Storefront Namespace
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/sdk#tenant" className={() => (hash === "#tenant" ? "active" : "")}>
                    Tenant Management
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/sdk#platform" className={() => (hash === "#platform" ? "active" : "")}>
                    Platform Operations
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/sdk#ecommerce" className={() => (hash === "#ecommerce" ? "active" : "")}>
                    E-Commerce Helpers
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/sdk#errors" className={() => (hash === "#errors" ? "active" : "")}>
                    Errors
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/sdk#examples" className={() => (hash === "#examples" ? "active" : "")}>
                    Runnable Examples
                  </NavLink>
                </li>
              </ul>
            </div>

            <div className="docs-nav-group">
              <div className="docs-nav-heading">Guides & Architecture</div>
              <ul className="docs-nav-list">
                <li>
                  <NavLink to="/docs/guides" end className={({ isActive }) => (isActive ? "active" : "")}>
                    All Guides
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/guides#event-ingestion" className={() => (hash === "#event-ingestion" ? "active" : "")}>
                    Interaction Event Ingestion
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/guides#recommendation-strategies" className={() => (hash === "#recommendation-strategies" ? "active" : "")}>
                    Recommendation Strategies
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/guides#cold-start" className={() => (hash === "#cold-start" ? "active" : "")}>
                    Cold-Start & Fallbacks
                  </NavLink>
                </li>
                <li>
                  <NavLink to="/docs/guides#retries-errors" className={() => (hash === "#retries-errors" ? "active" : "")}>
                    Retries & Observability
                  </NavLink>
                </li>
              </ul>
            </div>

            <div className="docs-nav-group">
              <div className="docs-nav-heading">Resources</div>
              <ul className="docs-nav-list">
                <li>
                  <NavLink to="/docs/errors-and-limits" className={({ isActive }) => (isActive ? "active" : "")}>
                    Errors, Limits & Changelog
                  </NavLink>
                </li>
                <li>
                  <Link to="/pricing">Pricing Plans</Link>
                </li>
              </ul>
            </div>
          </div>
        </aside>

        {/* Content Area */}
        <main className="docs-main" id="main-content" tabIndex={-1}>
          <div className="docs-article">{children ?? <Outlet />}</div>
        </main>

        {/* Right Sticky TOC */}
        <aside className="docs-toc">
          {tocItems.length > 0 && (
            <div className="docs-toc-sticky">
              <div className="docs-toc-heading">On this page</div>
              <ul className="docs-toc-list">
                {tocItems.map((item) => (
                  <li key={item.id} className={`docs-toc-item level-${item.level} ${activeHeading === item.id ? "active" : ""}`}>
                    <a href={`#${item.id}`}>{item.label}</a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>

      <DocsSearchModal isOpen={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  );
}
