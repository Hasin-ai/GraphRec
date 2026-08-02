import { useState } from "react";
import { getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { SpaLink } from "../components/SpaLink";

function labelForRole(role: string): string {
  return role.replaceAll("_", " ");
}

export function AppPage() {
  const session = getAuthSession();
  const [activeTab, setActiveTab] = useState<"resources" | "activity" | "settings">("resources");

  if (!session) {
    const returnTo = encodeURIComponent(`${window.location.pathname}${window.location.search}`);
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in to open this workspace.</h1>
        <p className="lede compact">This browser has no active in-memory GraphRec session.</p>
        <a className="button primary" href={`/auth/login?returnTo=${returnTo}`}>
          Sign in
        </a>
      </main>
    );
  }

  return (
    <main className="workspace-shell">
      <Navbar />

      {/* DigitalOcean Project Header */}
      <section className="workspace-hero" style={{ paddingBottom: "0.5rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1rem" }}>
          <div>
            <h1 style={{ fontSize: "1.75rem", fontWeight: 800, margin: 0 }}>Northwind Project</h1>
            <p className="lede" style={{ margin: "0.25rem 0 0", fontSize: "0.92rem", color: "#64748b" }}>
              <span>Welcome to GraphRec.</span> Signed in as <strong>{labelForRole(session.user_role)}</strong>. Control data ingestion, model versions, and API keys.
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <SpaLink className="button primary" href="/app/models" style={{ fontSize: "0.88rem", padding: "0.5rem 1.1rem" }}>
              + Add Resource
            </SpaLink>
          </div>
        </div>

        {/* DigitalOcean Project Tabs */}
        <div style={{ display: "flex", gap: "1.5rem", borderBottom: "1px solid #e2e8f0", marginTop: "1.25rem", paddingBottom: "0.5rem" }}>
          <button
            type="button"
            onClick={() => setActiveTab("resources")}
            style={{
              background: "none",
              border: "none",
              borderBottom: activeTab === "resources" ? "2px solid #0069ff" : "2px solid transparent",
              color: activeTab === "resources" ? "#0069ff" : "#64748b",
              fontWeight: 600,
              fontSize: "0.9rem",
              padding: "0.4rem 0.2rem",
              cursor: "pointer",
            }}
          >
            Resources (3)
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("activity")}
            style={{
              background: "none",
              border: "none",
              borderBottom: activeTab === "activity" ? "2px solid #0069ff" : "2px solid transparent",
              color: activeTab === "activity" ? "#0069ff" : "#64748b",
              fontWeight: 600,
              fontSize: "0.9rem",
              padding: "0.4rem 0.2rem",
              cursor: "pointer",
            }}
          >
            Activity Feed
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("settings")}
            style={{
              background: "none",
              border: "none",
              borderBottom: activeTab === "settings" ? "2px solid #0069ff" : "2px solid transparent",
              color: activeTab === "settings" ? "#0069ff" : "#64748b",
              fontWeight: 600,
              fontSize: "0.9rem",
              padding: "0.4rem 0.2rem",
              cursor: "pointer",
            }}
          >
            Project Settings
          </button>
        </div>
      </section>

      {/* Main Two-Column DigitalOcean Layout */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", gap: "1.5rem", marginTop: "1.5rem" }}>
        
        {/* Left Primary Resources Column */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          
          {activeTab === "resources" ? (
            <>
              {/* DigitalOcean Style Resources Table */}
              <div style={{ background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: "8px", overflow: "hidden" }}>
                <div style={{ padding: "1rem 1.25rem", borderBottom: "1px solid #e2e8f0", background: "#f8fafc", fontWeight: 700, fontSize: "0.85rem", color: "#475569" }}>
                  ACTIVE PROJECT RESOURCES
                </div>

                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "0.88rem" }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid #e2e8f0", color: "#64748b", fontSize: "0.75rem", textTransform: "uppercase" }}>
                        <th style={{ padding: "0.75rem 1.25rem" }}>Resource Name</th>
                        <th style={{ padding: "0.75rem 1.25rem" }}>Type</th>
                        <th style={{ padding: "0.75rem 1.25rem" }}>Specifications</th>
                        <th style={{ padding: "0.75rem 1.25rem" }}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "0.85rem 1.25rem", fontWeight: 600, color: "#0069ff" }}>
                          <SpaLink href="/app/deployment">gnn-recommendation-v2</SpaLink>
                        </td>
                        <td style={{ padding: "0.85rem 1.25rem", color: "#475569" }}>Inference Endpoint</td>
                        <td style={{ padding: "0.85rem 1.25rem", color: "#64748b" }}>2 vCPU - 4 GB RAM (14ms SLA)</td>
                        <td style={{ padding: "0.85rem 1.25rem" }}>
                          <span style={{ background: "#ecfdf5", color: "#047857", fontSize: "0.75rem", fontWeight: 700, padding: "0.2rem 0.5rem", borderRadius: "4px" }}>
                            ● Active
                          </span>
                        </td>
                      </tr>
                      <tr style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <td style={{ padding: "0.85rem 1.25rem", fontWeight: 600, color: "#0069ff" }}>
                          <SpaLink href="/app/data">products-snapshot-20260801</SpaLink>
                        </td>
                        <td style={{ padding: "0.85rem 1.25rem", color: "#475569" }}>Dataset Snapshot</td>
                        <td style={{ padding: "0.85rem 1.25rem", color: "#64748b" }}>1.2M Events - 45K Products</td>
                        <td style={{ padding: "0.85rem 1.25rem" }}>
                          <span style={{ background: "#ecfdf5", color: "#047857", fontSize: "0.75rem", fontWeight: 700, padding: "0.2rem 0.5rem", borderRadius: "4px" }}>
                            ● Indexed
                          </span>
                        </td>
                      </tr>
                      <tr>
                        <td style={{ padding: "0.85rem 1.25rem", fontWeight: 600, color: "#0069ff" }}>
                          <SpaLink href="/app/integration/api-keys">production-store-key</SpaLink>
                        </td>
                        <td style={{ padding: "0.85rem 1.25rem", color: "#475569" }}>API Key Credential</td>
                        <td style={{ padding: "0.85rem 1.25rem", color: "#64748b" }}>catalog:read, events:write</td>
                        <td style={{ padding: "0.85rem 1.25rem" }}>
                          <span style={{ background: "#ecfdf5", color: "#047857", fontSize: "0.75rem", fontWeight: 700, padding: "0.2rem 0.5rem", borderRadius: "4px" }}>
                            ● Active
                          </span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Resource Cards Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1rem" }}>
                <section className="workspace-action-card" style={{ padding: "1.25rem" }}>
                  <p className="eyebrow" style={{ fontSize: "0.72rem" }}>Data & Ingestion</p>
                  <h2 style={{ fontSize: "1.15rem", marginBottom: "0.4rem" }}>Database Upload & Events</h2>
                  <p style={{ fontSize: "0.85rem", color: "#64748b", lineHeight: 1.5 }}>
                    Upload product databases (CSV/JSON) and submit customer interaction event batches.
                  </p>
                  <SpaLink className="button primary" href="/app/data" style={{ marginTop: "1rem", width: "100%" }}>
                    Open Data Upload
                  </SpaLink>
                </section>

                <section className="workspace-action-card" style={{ padding: "1.25rem" }}>
                  <p className="eyebrow" style={{ fontSize: "0.72rem" }}>ML Engineering</p>
                  <h2 style={{ fontSize: "1.15rem", marginBottom: "0.4rem" }}>Model Upload & Registry</h2>
                  <p style={{ fontSize: "0.85rem", color: "#64748b", lineHeight: 1.5 }}>
                    Upload model artifacts, activate versions, rollback revisions, and launch training runs.
                  </p>
                  <SpaLink className="button primary" href="/app/models" style={{ marginTop: "1rem", width: "100%" }}>
                    Open Model Registry
                  </SpaLink>
                </section>
              </div>
            </>
          ) : activeTab === "activity" ? (
            <div className="do-summary-card">
              <h3 style={{ fontSize: "1rem", marginBottom: "0.75rem" }}>Recent Project Events</h3>
              <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: "0.88rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                <li style={{ paddingBottom: "0.75rem", borderBottom: "1px solid #e2e8f0" }}>
                  <strong>Model Endpoint Deployed</strong> — <code>gnn-recommendation-v2</code> is live (14ms SLA).
                </li>
                <li style={{ paddingBottom: "0.75rem", borderBottom: "1px solid #e2e8f0" }}>
                  <strong>Snapshot Created</strong> — Indexed 1,250,000 interaction events.
                </li>
                <li>
                  <strong>API Key Generated</strong> — <code>production-store-key</code> issued.
                </li>
              </ul>
            </div>
          ) : null}

          {/* Granted Authorization Scopes Card */}
          <section className="scope-card" aria-labelledby="scope-heading" style={{ padding: "1.5rem" }}>
            <div>
              <p className="eyebrow">Credential-derived authorization</p>
              <h2 id="scope-heading" style={{ fontSize: "1.2rem" }}>Granted scopes</h2>
            </div>
            <ul className="scope-list" style={{ marginTop: "0.75rem" }}>
              {session.scopes.map((scope) => (
                <li key={scope}>{scope}</li>
              ))}
            </ul>
          </section>

          {/* Quick Access Feature Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "1rem" }}>
            {session.scopes.includes("billing:read") ? (
              <section className="workspace-action-card" style={{ padding: "1.25rem" }}>
                <p className="eyebrow" style={{ fontSize: "0.72rem" }}>Protected feature</p>
                <h2 style={{ fontSize: "1.1rem", marginBottom: "0.4rem" }}>Subscription and quotas</h2>
                <p style={{ fontSize: "0.85rem", color: "#64748b" }}>Review demonstration plan limits.</p>
                <SpaLink className="button primary" href="/app/subscription" style={{ marginTop: "0.85rem", width: "100%" }}>
                  View subscription
                </SpaLink>
              </section>
            ) : null}

            {session.scopes.includes("usage:read") ? (
              <section className="workspace-action-card" style={{ padding: "1.25rem" }}>
                <p className="eyebrow" style={{ fontSize: "0.72rem" }}>Protected feature</p>
                <h2 style={{ fontSize: "1.1rem", marginBottom: "0.4rem" }}>Current usage</h2>
                <p style={{ fontSize: "0.85rem", color: "#64748b" }}>Review reconciled counters.</p>
                <SpaLink className="button primary" href="/app/usage" style={{ marginTop: "0.85rem", width: "100%" }}>
                  View usage
                </SpaLink>
              </section>
            ) : null}

            {session.scopes.includes("keys:write") ? (
              <section className="workspace-action-card" style={{ padding: "1.25rem" }}>
                <p className="eyebrow" style={{ fontSize: "0.72rem" }}>Protected feature</p>
                <h2 style={{ fontSize: "1.1rem", marginBottom: "0.4rem" }}>API keys</h2>
                <p style={{ fontSize: "0.85rem", color: "#64748b" }}>Manage scoped server tokens.</p>
                <SpaLink className="button primary" href="/app/integration/api-keys" style={{ marginTop: "0.85rem", width: "100%" }}>
                  Manage API keys
                </SpaLink>
              </section>
            ) : null}
          </div>
        </div>

        {/* Right DigitalOcean Summary Sidebar Panel (Matching the user screenshot!) */}
        <div>
          <div className="do-summary-card" style={{ position: "sticky", top: "76px" }}>
            <h3 style={{ fontSize: "1rem", fontWeight: 700, margin: "0 0 1rem", color: "#1e293b", paddingBottom: "0.75rem", borderBottom: "1px solid #e2e8f0" }}>
              Project Summary
            </h3>

            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", fontSize: "0.88rem" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>Plan Tier:</span>
                <strong>Enterprise Basic</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>Monthly Cost:</span>
                <strong>$32.00/mo</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>vCPU Compute:</span>
                <strong>4 Cores</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>RAM Allocation:</span>
                <strong>16 GB</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>NVMe Storage:</span>
                <strong>120 GB SSD</strong>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>Bandwidth:</span>
                <strong>4 TB Transfer</strong>
              </div>
            </div>

            <div style={{ margin: "1.25rem 0", padding: "0.85rem", background: "#f0f6ff", border: "1px solid #bfdbfe", borderRadius: "6px", fontSize: "0.85rem", color: "#1e40af" }}>
              💡 <strong>SSH Key & Security:</strong> API keys use RSA-2048 signing and column-level PostgreSQL RLS.
            </div>

            <SpaLink className="button primary" href="/app/models" style={{ width: "100%", justifyContent: "center" }}>
              Create Endpoint
            </SpaLink>
          </div>
        </div>

      </div>

      <p className="session-note" style={{ marginTop: "2.5rem", color: "#94a3b8", fontSize: "0.82rem" }}>
        Tokens are held in memory only and disappear on refresh. Refresh and server-side logout endpoints remain API pending.
      </p>
    </main>
  );
}
