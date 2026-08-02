import { useEffect, useState } from "react";
import {
  getAutoscalingStatus,
  getDeploymentStatus,
  getReplicaStatus,
  type AutoscalingStatus,
  type DeploymentStatus,
  type ReplicaStatusResponse,
} from "../api/deployment";
import { getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";

export function DeploymentPage() {
  const session = getAuthSession();
  const [deployment, setDeployment] = useState<DeploymentStatus | null>(null);
  const [replicas, setReplicas] = useState<ReplicaStatusResponse | null>(null);
  const [autoscaling, setAutoscaling] = useState<AutoscalingStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      void loadDeploymentData();
    }
  }, [session]);

  async function loadDeploymentData() {
    if (!session) return;
    setIsLoading(true);
    try {
      const [d, r, a] = await Promise.all([
        getDeploymentStatus(session.access_token),
        getReplicaStatus(session.access_token),
        getAutoscalingStatus(session.access_token),
      ]);
      setDeployment(d);
      setReplicas(r);
      setAutoscaling(a);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load deployment overview");
    } finally {
      setIsLoading(false);
    }
  }

  if (!session) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in to view deployment and replica status.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fapp%2Fdeployment">
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
          <p className="eyebrow">Operations / Deployment</p>
          <h1>Deployment & Replica Status</h1>
          <p className="lede compact">
            Monitor real-time model rollout, active/desired versions, pod replicas, and HPA autoscaling.
          </p>
        </div>
        <div className="page-actions">
          <button className="button secondary" type="button" onClick={() => void loadDeploymentData()} disabled={isLoading}>
            {isLoading ? "Refreshing…" : "Refresh Operations"}
          </button>
        </div>
      </section>

      {error ? (
        <div className="error-panel" role="alert" style={{ marginBottom: "1.5rem" }}>
          <strong>Deployment Error</strong>
          <p>{error}</p>
        </div>
      ) : null}

      {/* Deployment Status Card */}
      {deployment ? (
        <section className="plan-summary" style={{ marginBottom: "2rem" }}>
          <div>
            <p className="eyebrow">Current Deployment State</p>
            <h2>Serving Status: {deployment.status.toUpperCase()}</h2>
          </div>
          <dl>
            <div>
              <dt>Active Model Version</dt>
              <dd><code>{deployment.active_model_version_id || "None (Popular Fallback)"}</code></dd>
            </div>
            <div>
              <dt>Desired Model Version</dt>
              <dd><code>{deployment.desired_model_version_id || "None"}</code></dd>
            </div>
            <div>
              <dt>Desired Replicas</dt>
              <dd>{deployment.desired_replicas}</dd>
            </div>
            <div>
              <dt>Ready Replicas</dt>
              <dd><span className="status-badge">{deployment.ready_replicas} / {deployment.current_replicas}</span></dd>
            </div>
          </dl>
        </section>
      ) : null}

      {/* Replicas List */}
      {replicas ? (
        <section className="limits-card" style={{ marginBottom: "2rem" }}>
          <div className="limits-card-heading">
            <p className="eyebrow">Active Pod Replicas</p>
            <h2>Replicas ({replicas.replicas.length})</h2>
          </div>
          <div className="key-list">
            {replicas.replicas.map((rep) => (
              <article className="key-card" key={rep.id}>
                <div className="key-card-title">
                  <div>
                    <h2>{rep.id}</h2>
                    <code>Started: {new Date(rep.started_at).toLocaleString()}</code>
                  </div>
                  <span className={`key-status ${rep.ready ? "key-active" : "key-expired"}`}>
                    {rep.status}
                  </span>
                </div>
                <dl className="key-metadata">
                  <div>
                    <dt>Pinned Model Version</dt>
                    <dd><code>{rep.model_version_id ? rep.model_version_id.substring(0, 8) : "N/A"}</code></dd>
                  </div>
                  <div>
                    <dt>Health State</dt>
                    <dd>{rep.ready ? "Healthy & Serving" : "Initializing"}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {/* Autoscaling Status */}
      {autoscaling ? (
        <section className="limits-card">
          <div className="limits-card-heading">
            <p className="eyebrow">Autoscaling Policy</p>
            <h2>HPA State & Capacity</h2>
          </div>
          <dl className="key-metadata" style={{ padding: "1rem" }}>
            <div>
              <dt>Min / Max Replicas</dt>
              <dd>{autoscaling.min_replicas} / {autoscaling.max_replicas}</dd>
            </div>
            <div>
              <dt>CPU Target Threshold</dt>
              <dd>{autoscaling.cpu_target_percent}%</dd>
            </div>
            <div>
              <dt>Capacity Blocked</dt>
              <dd>{autoscaling.capacity_blocked ? "BLOCKED" : "Normal"}</dd>
            </div>
          </dl>
        </section>
      ) : null}
    </main>
  );
}
