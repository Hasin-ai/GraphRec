import { useEffect, useState } from "react";
import { createTrainingJob, listTrainingJobs } from "../api/models";
import { listDatasetSnapshots, type DatasetSnapshotResource } from "../api/datasets";
import type { TrainingJobResource } from "../api/types";
import { getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";

export function TrainingPage() {
  const session = getAuthSession();
  const [jobs, setJobs] = useState<TrainingJobResource[]>([]);
  const [snapshots, setSnapshots] = useState<DatasetSnapshotResource[]>([]);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string>("");
  const [modelType, setModelType] = useState("simplified_dgsr");
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      void loadData();
    }
  }, [session]);

  async function loadData() {
    if (!session) return;
    setIsLoading(true);
    try {
      const [jRes, sRes] = await Promise.all([
        listTrainingJobs(session.access_token),
        listDatasetSnapshots(session.access_token),
      ]);
      setJobs(jRes.items);
      setSnapshots(sRes.items);
      if (sRes.items.length > 0 && !selectedSnapshotId) {
        setSelectedSnapshotId(sRes.items[0].id);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load training pipeline data");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleLaunch() {
    if (!session) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await createTrainingJob(session.access_token, {
        model_type: modelType,
        dataset_snapshot_id: selectedSnapshotId || undefined,
        configuration: { batch_size: 256, learning_rate: 0.001, gnn_layers: 2 },
      });
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start training job");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!session) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in to manage training jobs.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fapp%2Ftraining">
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
          <p className="eyebrow">ML Engineering / Training Pipeline</p>
          <h1>Model Training & Snapshot Pipeline</h1>
          <p className="lede compact">Select an immutable dataset snapshot and launch DGSR-lite offline model training.</p>
        </div>
        <div className="page-actions">
          <button className="button secondary" type="button" onClick={() => void loadData()} disabled={isLoading}>
            {isLoading ? "Refreshing…" : "Refresh Pipeline"}
          </button>
        </div>
      </section>

      {error ? (
        <div className="error-panel" role="alert" style={{ marginBottom: "1.5rem" }}>
          <strong>Training Error</strong>
          <p>{error}</p>
        </div>
      ) : null}

      {/* Training Configuration Panel */}
      <section className="auth-card" style={{ maxWidth: "none", margin: "0 0 2rem" }}>
        <h2>Launch Model Training Job</h2>
        <p className="form-note">
          Choose a dynamic graph algorithm and binding dataset snapshot to train your recommendation model.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", margin: "1rem 0" }}>
          <div>
            <label htmlFor="model-type-select">Model Architecture</label>
            <select
              id="model-type-select"
              value={modelType}
              onChange={(e) => setModelType(e.target.value)}
              style={{ width: "100%", padding: "0.6rem", borderRadius: "0.6rem", border: "1px solid var(--line)" }}
            >
              <option value="simplified_dgsr">Simplified DGSR (PyG Dynamic Graph GNN)</option>
              <option value="bpr_matrix_factorization">BPR Matrix Factorization</option>
              <option value="item_knn_popular">Item KNN & Popularity</option>
            </select>
          </div>

          <div>
            <label htmlFor="snapshot-select">Target Dataset Snapshot</label>
            <select
              id="snapshot-select"
              value={selectedSnapshotId}
              onChange={(e) => setSelectedSnapshotId(e.target.value)}
              style={{ width: "100%", padding: "0.6rem", borderRadius: "0.6rem", border: "1px solid var(--line)" }}
            >
              {snapshots.length === 0 ? (
                <option value="">Auto-create Snapshot on Launch</option>
              ) : (
                snapshots.map((s) => (
                  <option key={s.id} value={s.id}>
                    Snapshot {s.id.substring(0, 8)}… ({s.event_count} events, {s.product_count} products)
                  </option>
                ))
              )}
            </select>
          </div>
        </div>

        <button
          className="button primary"
          type="button"
          onClick={() => void handleLaunch()}
          disabled={isSubmitting}
        >
          {isSubmitting ? "Executing Training Pipeline…" : "Execute Training Pipeline"}
        </button>
      </section>

      {/* History */}
      <section className="limits-card">
        <div className="limits-card-heading">
          <p className="eyebrow">Training History</p>
          <h2>All Training Runs ({jobs.length})</h2>
        </div>
        {jobs.length === 0 ? (
          <div className="empty-keys" role="status" style={{ marginTop: "1rem" }}>
            <h2>No training jobs executed</h2>
            <p>Select a dataset snapshot above and execute your first model training pipeline.</p>
          </div>
        ) : (
          <div className="key-list">
            {jobs.map((job) => (
              <article className="key-card" key={job.id}>
                <div className="key-card-title">
                  <div>
                    <h2>{job.model_type}</h2>
                    <code>Job ID: {job.id}</code>
                  </div>
                  <span className="key-status key-active">{job.status}</span>
                </div>
                <dl className="key-metadata">
                  <div>
                    <dt>Started At</dt>
                    <dd>{new Date(job.created_at).toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt>Dataset Snapshot ID</dt>
                    <dd><code>{job.dataset_snapshot_id ? job.dataset_snapshot_id.substring(0, 8) : "Auto-Generated"}</code></dd>
                  </div>
                  <div>
                    <dt>Model Version ID</dt>
                    <dd><code>{job.model_version_id ? job.model_version_id.substring(0, 8) : "None"}</code></dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
