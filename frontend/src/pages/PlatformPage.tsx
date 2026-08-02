import { useEffect, useState } from "react";
import {
  getPlatformStatus,
  listPlatformAuditLogs,
  listPlatformFailures,
  listPlatformPlans,
  listPlatformTenants,
  type PlatformAudit,
  type PlatformFailure,
  type PlatformPlan,
  type PlatformTenant,
} from "../api/platform";
import { getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";

export function PlatformPage() {
  const session = getAuthSession();
  const [tenants, setTenants] = useState<PlatformTenant[]>([]);
  const [plans, setPlans] = useState<PlatformPlan[]>([]);
  const [failures, setFailures] = useState<PlatformFailure[]>([]);
  const [auditLogs, setAuditLogs] = useState<PlatformAudit[]>([]);
  const [platformStatus, setPlatformStatus] = useState<Record<string, unknown> | null>(null);
  const [activeTab, setActiveTab] = useState<"tenants" | "plans" | "failures" | "audit" | "status">("tenants");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      void loadPlatformData();
    }
  }, [session]);

  async function loadPlatformData() {
    if (!session) return;
    setIsLoading(true);
    try {
      const [t, p, f, a, s] = await Promise.all([
        listPlatformTenants(session.access_token),
        listPlatformPlans(session.access_token),
        listPlatformFailures(session.access_token),
        listPlatformAuditLogs(session.access_token),
        getPlatformStatus(),
      ]);
      setTenants(t.items);
      setPlans(p);
      setFailures(f.items);
      setAuditLogs(a.items);
      setPlatformStatus(s);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load platform portal");
    } finally {
      setIsLoading(false);
    }
  }

  if (!session) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in as Platform Administrator.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fplatform">
          Sign in
        </a>
      </main>
    );
  }

  return (
    <main className="workspace-shell">
      <Navbar />
      <section className="subscription-heading">
        <div>
          <p className="eyebrow">Platform Administration</p>
          <h1>Platform Overview & Controls</h1>
          <p className="lede compact">Global tenant management, plan defaults, failure tracking, and audit logs.</p>
        </div>
        <div className="page-actions">
          <button className="button secondary" type="button" onClick={() => void loadPlatformData()} disabled={isLoading}>
            {isLoading ? "Refreshing…" : "Refresh Portal"}
          </button>
        </div>
      </section>

      {/* Tabs Header */}
      <div className="page-actions" style={{ marginBottom: "1.5rem" }}>
        <button
          className={`button ${activeTab === "tenants" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("tenants")}
        >
          Tenants ({tenants.length})
        </button>
        <button
          className={`button ${activeTab === "plans" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("plans")}
        >
          Plans & Quotas
        </button>
        <button
          className={`button ${activeTab === "failures" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("failures")}
        >
          Failures ({failures.length})
        </button>
        <button
          className={`button ${activeTab === "audit" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("audit")}
        >
          Audit Logs ({auditLogs.length})
        </button>
        <button
          className={`button ${activeTab === "status" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("status")}
        >
          System Health
        </button>
      </div>

      {error ? (
        <div className="error-panel" role="alert" style={{ marginBottom: "1.5rem" }}>
          <strong>Platform Error</strong>
          <p>{error}</p>
        </div>
      ) : null}

      {activeTab === "tenants" ? (
        <section className="limits-card">
          <div className="limits-card-heading">
            <p className="eyebrow">Tenant Directory</p>
            <h2>Registered Platform Tenants</h2>
          </div>
          <div className="key-list">
            {tenants.map((t) => (
              <article className="key-card" key={t.id}>
                <div className="key-card-title">
                  <div>
                    <h2>{t.name}</h2>
                    <code>{t.slug}</code>
                  </div>
                  <span className="key-status key-active">{t.status}</span>
                </div>
                <dl className="key-metadata">
                  <div>
                    <dt>Tenant ID</dt>
                    <dd><code>{t.id}</code></dd>
                  </div>
                  <div>
                    <dt>Created At</dt>
                    <dd>{new Date(t.created_at).toLocaleString()}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {activeTab === "plans" ? (
        <section className="limits-card">
          <div className="limits-card-heading">
            <p className="eyebrow">Pricing Plans</p>
            <h2>Configured Demonstration Plans</h2>
          </div>
          <div className="key-list">
            {plans.map((p) => (
              <article className="key-card" key={p.id}>
                <div className="key-card-title">
                  <div>
                    <h2>{p.name}</h2>
                    <code>{p.code}</code>
                  </div>
                  <span className="key-status key-active">{p.is_active ? "Active" : "Disabled"}</span>
                </div>
                <dl className="key-metadata">
                  <div>
                    <dt>Limits</dt>
                    <dd>{JSON.stringify(p.limits)}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {activeTab === "failures" ? (
        <section className="limits-card">
          <div className="limits-card-heading">
            <p className="eyebrow">Redacted Failures</p>
            <h2>System Failures & Security Events</h2>
          </div>
          <div className="key-list">
            {failures.length === 0 ? (
              <p style={{ padding: "1rem" }}>No system failures recorded.</p>
            ) : (
              failures.map((f) => (
                <article className="key-card" key={f.id}>
                  <div className="key-card-title">
                    <div>
                      <h2>{f.event_type}</h2>
                      <code>Severity: {f.severity}</code>
                    </div>
                    <span>{new Date(f.occurred_at).toLocaleString()}</span>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      ) : null}

      {activeTab === "audit" ? (
        <section className="limits-card">
          <div className="limits-card-heading">
            <p className="eyebrow">Audit Trail</p>
            <h2>Platform Administrative Actions</h2>
          </div>
          <div className="key-list">
            {auditLogs.length === 0 ? (
              <p style={{ padding: "1rem" }}>No audit log events recorded.</p>
            ) : (
              auditLogs.map((a) => (
                <article className="key-card" key={a.id}>
                  <div className="key-card-title">
                    <div>
                      <h2>{a.action_type} on {a.resource_type}</h2>
                      <code>Outcome: {a.outcome}</code>
                    </div>
                    <span>{new Date(a.occurred_at).toLocaleString()}</span>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      ) : null}

      {activeTab === "status" && platformStatus ? (
        <section className="plan-summary">
          <div>
            <p className="eyebrow">System Health</p>
            <h2>Overall Platform Status</h2>
          </div>
          <dl>
            <div>
              <dt>API Cluster</dt>
              <dd><span className="status-badge">{String(platformStatus.api_cluster)}</span></dd>
            </div>
            <div>
              <dt>Database</dt>
              <dd>{String(platformStatus.database)}</dd>
            </div>
            <div>
              <dt>Worker Pool</dt>
              <dd>{String(platformStatus.worker_pool)}</dd>
            </div>
          </dl>
        </section>
      ) : null}
    </main>
  );
}
