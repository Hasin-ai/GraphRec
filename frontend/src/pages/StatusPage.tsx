import { useEffect, useState } from "react";
import { getMetricsSummary, type MetricsSummary } from "../api/deployment";
import { getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";

export function StatusPage() {
  const session = getAuthSession();
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      void loadMetrics();
    }
  }, [session]);

  async function loadMetrics() {
    if (!session) return;
    setIsLoading(true);
    try {
      const data = await getMetricsSummary(session.access_token);
      setMetrics(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load tenant metrics");
    } finally {
      setIsLoading(false);
    }
  }

  if (!session) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in to view tenant metrics & service status.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fapp%2Fstatus">
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
          <p className="eyebrow">Metrics & Status</p>
          <h1>Tenant Operational Metrics & Service Status</h1>
          <p className="lede compact">
            Real-time operational latency, request rate, fallback frequency, and model quality metrics.
          </p>
        </div>
        <div className="page-actions">
          <button className="button secondary" type="button" onClick={() => void loadMetrics()} disabled={isLoading}>
            {isLoading ? "Refreshing…" : "Refresh Metrics"}
          </button>
        </div>
      </section>

      {error ? (
        <div className="error-panel" role="alert" style={{ marginBottom: "1.5rem" }}>
          <strong>Metrics Error</strong>
          <p>{error}</p>
        </div>
      ) : null}

      {metrics ? (
        <>
          <section className="plan-summary" style={{ marginBottom: "2rem" }}>
            <div>
              <p className="eyebrow">Operational Performance</p>
              <h2>Real-Time Traffic Metrics</h2>
            </div>
            <dl>
              <div>
                <dt>Request Rate</dt>
                <dd><span className="status-badge">{metrics.request_rate} req/s</span></dd>
              </div>
              <div>
                <dt>P95 Latency</dt>
                <dd>{metrics.p95_latency_ms} ms</dd>
              </div>
              <div>
                <dt>Error Rate</dt>
                <dd>{(metrics.error_rate * 100).toFixed(2)}%</dd>
              </div>
              <div>
                <dt>Fallback Rate</dt>
                <dd>{(metrics.fallback_rate * 100).toFixed(2)}%</dd>
              </div>
            </dl>
          </section>

          {metrics.quality ? (
            <section className="limits-card">
              <div className="limits-card-heading">
                <p className="eyebrow">Offline Quality Metrics</p>
                <h2>Recommendation Quality Metrics</h2>
              </div>
              <div className="key-list">
                <article className="key-card">
                  <dl className="key-metadata">
                    <div>
                      <dt>Hit@10</dt>
                      <dd>{metrics.quality.hit_at_10}</dd>
                    </div>
                    <div>
                      <dt>NDCG@10</dt>
                      <dd>{metrics.quality.ndcg_at_10}</dd>
                    </div>
                    <div>
                      <dt>Recall@K</dt>
                      <dd>{metrics.quality.retrieval_recall_at_k}</dd>
                    </div>
                    <div>
                      <dt>Catalog Coverage</dt>
                      <dd>{(metrics.quality.catalog_coverage * 100).toFixed(1)}%</dd>
                    </div>
                    <div>
                      <dt>Diversity Score</dt>
                      <dd>{metrics.quality.intra_list_diversity}</dd>
                    </div>
                  </dl>
                </article>
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
