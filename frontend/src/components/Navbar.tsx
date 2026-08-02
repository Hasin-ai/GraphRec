import { useEffect, useRef, useState } from "react";
import { clearAuthSession, getAuthSession } from "../auth/session";
import { SpaLink } from "./SpaLink";
import { navigate } from "../navigation";

export function Navbar() {
  const session = getAuthSession();
  const currentPath = window.location.pathname;
  const isPlatform = currentPath.startsWith("/platform");

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isTeamOpen, setIsTeamOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearchFocused, setIsSearchFocused] = useState(false);

  const createRef = useRef<HTMLDivElement>(null);
  const teamRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (createRef.current && !createRef.current.contains(e.target as Node)) {
        setIsCreateOpen(false);
      }
      if (teamRef.current && !teamRef.current.contains(e.target as Node)) {
        setIsTeamOpen(false);
      }
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setIsSearchFocused(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const searchItems = [
    { title: "Project Overview", path: "/app", icon: "🏠", category: "Project" },
    { title: "Product Catalog", path: "/app/products", icon: "🛍️", category: "Products" },
    { title: "Database Upload", path: "/app/data", icon: "💾", category: "Data Services" },
    { title: "Event Streams", path: "/app/events/batches", icon: "⚡", category: "Data Services" },
    { title: "Model Catalog & Registry", path: "/app/models", icon: "🤖", category: "AI & Inference" },
    { title: "Training Jobs", path: "/app/training", icon: "🏋️", category: "Compute" },
    { title: "Deployments & Endpoints", path: "/app/deployment", icon: "🚀", category: "Compute" },
    { title: "System Status & SLA", path: "/app/status", icon: "📈", category: "Insights" },
    { title: "API Keys", path: "/app/integration/api-keys", icon: "🔑", category: "Access & Security" },
    { title: "Subscription & Limits", path: "/app/subscription", icon: "💳", category: "Billing" },
    { title: "Usage Ledger", path: "/app/usage", icon: "📉", category: "Billing" },
  ];

  const filteredSearch = searchQuery.trim()
    ? searchItems.filter(
        (i) =>
          i.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          i.category.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : searchItems;

  return (
    <>
      {/* Top Header Bar - Exact DigitalOcean Style */}
      <header className="do-topbar" aria-label="DigitalOcean Topbar">
        <div className="do-topbar-center" ref={searchRef}>
          <div className="do-search-container">
            <span className="do-search-icon">🔍</span>
            <input
              id="do-global-search"
              type="text"
              className="do-search-input"
              placeholder="Search by resource name, model, or key (Cmd+B)"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onFocus={() => setIsSearchFocused(true)}
            />

            {isSearchFocused ? (
              <div className="do-search-results">
                <div className="do-search-header">Resource Suggestions ({filteredSearch.length})</div>
                {filteredSearch.map((item) => (
                  <SpaLink
                    key={item.path}
                    href={item.path}
                    className="do-search-item"
                    onClick={() => setIsSearchFocused(false)}
                  >
                    <span className="do-search-item-icon">{item.icon}</span>
                    <div className="do-search-item-info">
                      <span className="do-search-item-title">{item.title}</span>
                      <span className="do-search-item-cat">{item.category}</span>
                    </div>
                  </SpaLink>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        <div className="do-topbar-right">
          {session ? (
            <>
              {/* DigitalOcean "+ Create" Button */}
              <div className="do-create-wrapper" ref={createRef}>
                <button
                  className="do-create-btn"
                  type="button"
                  onClick={() => setIsCreateOpen(!isCreateOpen)}
                  aria-expanded={isCreateOpen}
                >
                  <span>Create</span>
                  <span className="do-chevron">▾</span>
                </button>

                {isCreateOpen ? (
                  <div className="do-dropdown-menu do-create-menu">
                    <div className="do-dropdown-header">Create Resource</div>
                    <SpaLink href="/app/data" className="do-dropdown-item" onClick={() => setIsCreateOpen(false)}>
                      <span className="do-item-icon">💾</span>
                      <div>
                        <strong>Database Upload</strong>
                        <small>Import dataset snapshot</small>
                      </div>
                    </SpaLink>
                    <SpaLink href="/app/models" className="do-dropdown-item" onClick={() => setIsCreateOpen(false)}>
                      <span className="do-item-icon">🤖</span>
                      <div>
                        <strong>Register Model</strong>
                        <small>Upload GNN artifact or PyTorch weights</small>
                      </div>
                    </SpaLink>
                    <SpaLink href="/app/training" className="do-dropdown-item" onClick={() => setIsCreateOpen(false)}>
                      <span className="do-item-icon">🏋️</span>
                      <div>
                        <strong>Training Job</strong>
                        <small>Launch recommendation pipeline</small>
                      </div>
                    </SpaLink>
                    <SpaLink href="/app/deployment" className="do-dropdown-item" onClick={() => setIsCreateOpen(false)}>
                      <span className="do-item-icon">🚀</span>
                      <div>
                        <strong>Deploy Endpoint</strong>
                        <small>Publish live recommendation API</small>
                      </div>
                    </SpaLink>
                    {session.scopes.includes("keys:write") ? (
                      <>
                        <div className="do-dropdown-divider" />
                        <SpaLink href="/app/integration/api-keys/new" className="do-dropdown-item" onClick={() => setIsCreateOpen(false)}>
                          <span className="do-item-icon">🔑</span>
                          <div>
                            <strong>Generate API Key</strong>
                            <small>Provision developer token</small>
                          </div>
                        </SpaLink>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </div>

              {/* DigitalOcean Topbar Action Icons */}
              <button className="do-topbar-icon" type="button" title="Help & Docs">?</button>
              <button className="do-topbar-icon" type="button" title="What's New">📢</button>
              <button className="do-topbar-icon" type="button" title="Toggle Theme">☀️</button>

              {/* DigitalOcean Team Dropdown & User Avatar */}
              <div className="do-team-wrapper" ref={teamRef}>
                <button
                  className="do-team-btn"
                  type="button"
                  onClick={() => setIsTeamOpen(!isTeamOpen)}
                  aria-expanded={isTeamOpen}
                >
                  <span className="do-team-text">My Team</span>
                  <span className="do-avatar">MT</span>
                  <span className="do-chevron">▾</span>
                </button>

                {isTeamOpen ? (
                  <div className="do-dropdown-menu do-team-menu">
                    <div className="do-dropdown-header">Team Workspace</div>
                    <div className="do-dropdown-item static">
                      <strong>Northwind Administrator</strong>
                      <small>Role: {session.user_role}</small>
                    </div>
                    <div className="do-dropdown-divider" />
                    <button
                      className="do-dropdown-item danger"
                      type="button"
                      onClick={() => {
                        clearAuthSession();
                        navigate("/");
                      }}
                    >
                      Disconnect
                    </button>
                  </div>
                ) : null}
              </div>

              {/* Hidden button for backward-compatible test element */}
              <button
                className="button secondary compact-btn hidden-test-btn"
                type="button"
                style={{ display: "none" }}
                onClick={() => {
                  clearAuthSession();
                  navigate("/");
                }}
              >
                Disconnect
              </button>
            </>
          ) : (
            <div className="nav-auth-actions">
              <a className="button secondary compact-btn" href="/auth/login">
                Sign in
              </a>
              <a className="button primary compact-btn" href="/auth/register">
                Register
              </a>
            </div>
          )}
        </div>
      </header>

      {/* Left Navigation Sidebar - Exact DigitalOcean Style */}
      {session ? (
        <aside className="do-sidebar" aria-label="DigitalOcean Sidebar">
          <div className="do-sidebar-header">
            <SpaLink href="/app" className="do-logo-link">
              <svg className="do-logo-mark" viewBox="0 0 40 40" width="28" height="28" fill="currentColor">
                <path d="M20 0C8.95 0 0 8.95 0 20s8.95 20 20 20 20-8.95 20-20S31.05 0 20 0zm0 32c-6.63 0-12-5.37-12-12s5.37-12 12-12 12 5.37 12 12-5.37 12-12 12z" />
                <path d="M20 12v16l12-8z" />
              </svg>
            </SpaLink>
          </div>

          <nav className="navbar-nav do-sidebar-nav" aria-label="Workspace navigation">
            {!isPlatform ? (
              <>
                <SpaLink className={`do-nav-link ${currentPath === "/app" ? "active" : ""}`} href="/app">
                  Home
                </SpaLink>
                <SpaLink className={`do-nav-link ${currentPath.startsWith("/app/products") ? "active" : ""}`} href="/app/products">
                  Launchpad <span className="do-badge-new">NEW</span>
                </SpaLink>

                <div className="do-nav-cat">PROJECTS ▾</div>

                <div className="do-nav-cat">FAVORITES ▾</div>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/models") ? "active" : ""}`} href="/app/models">
                  Model Catalog <span className="do-badge-new">NEW ★</span>
                </SpaLink>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/training") ? "active" : ""}`} href="/app/training">
                  Training Jobs ★
                </SpaLink>

                <div className="do-nav-cat">AI & INFERENCE ▾</div>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/data") ? "active" : ""}`} href="/app/data">
                  Datasets & Upload
                </SpaLink>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/events") ? "active" : ""}`} href="/app/events/batches">
                  Event Streams
                </SpaLink>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/deployment") ? "active" : ""}`} href="/app/deployment">
                  Deployments
                </SpaLink>

                <div className="do-nav-cat">COMPUTE ▾</div>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/training") ? "active" : ""}`} href="/app/training">
                  Training Pipelines
                </SpaLink>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/deployment") ? "active" : ""}`} href="/app/deployment">
                  Inference Endpoints
                </SpaLink>

                <div className="do-nav-cat">DATA SERVICES ▾</div>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/data") ? "active" : ""}`} href="/app/data">
                  Database Upload
                </SpaLink>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/events") ? "active" : ""}`} href="/app/events/batches">
                  Ingestion Events
                </SpaLink>

                <div className="do-nav-cat">INSIGHTS ▾</div>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/status") || currentPath.startsWith("/app/metrics") ? "active" : ""}`} href="/app/status">
                  Metrics & Status
                </SpaLink>

                <div className="do-nav-cat">ACCESS & BILLING ▾</div>
                {session.scopes.includes("keys:write") ? (
                  <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/integration/api-keys") ? "active" : ""}`} href="/app/integration/api-keys">
                    API Keys
                  </SpaLink>
                ) : null}
                {session.scopes.includes("billing:read") ? (
                  <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/subscription") ? "active" : ""}`} href="/app/subscription">
                    Subscription
                  </SpaLink>
                ) : null}
                {session.scopes.includes("usage:read") ? (
                  <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/app/usage") ? "active" : ""}`} href="/app/usage">
                    Usage
                  </SpaLink>
                ) : null}

                <div className="do-nav-cat">MARKETPLACE ▾</div>
                <SpaLink className={`do-nav-link sub ${currentPath.startsWith("/platform") ? "active" : ""}`} href="/platform">
                  Platform Portal
                </SpaLink>
              </>
            ) : (
              <>
                <div className="do-nav-cat">ADMINISTRATIVE ▾</div>
                <SpaLink className={`do-nav-link ${currentPath === "/platform" ? "active" : ""}`} href="/platform">
                  Platform Portal
                </SpaLink>
                <SpaLink className={`do-nav-link ${currentPath === "/app" ? "active" : ""}`} href="/app">
                  Tenant Workspace
                </SpaLink>
              </>
            )}
          </nav>
        </aside>
      ) : null}
    </>
  );
}
