import { useEffect, useState } from "react";
import {
  activateModelVersion,
  archiveModelVersion,
  createTrainingJob,
  listModelVersions,
  listTrainingJobs,
  registerModelVersion,
  rollbackModel,
} from "../api/models";
import type { ModelVersionResource, TrainingJobResource } from "../api/types";
import { getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";

export function ModelUploadPage() {
  const session = getAuthSession();
  const [activeTab, setActiveTab] = useState<"upload" | "registry" | "training">("registry");
  const [versions, setVersions] = useState<ModelVersionResource[]>([]);
  const [trainingJobs, setTrainingJobs] = useState<TrainingJobResource[]>([]);

  // Form state
  const [versionTag, setVersionTag] = useState("");
  const [modelType, setModelType] = useState("simplified_dgsr");
  const [recall, setRecall] = useState("0.85");
  const [ndcg, setNdcg] = useState("0.78");
  const [loss, setLoss] = useState("0.15");
  const [artifactUri, setArtifactUri] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    if (session) {
      void loadData();
    }
  }, [session]);

  async function loadData() {
    if (!session) return;
    setIsRefreshing(true);
    try {
      const [vData, tData] = await Promise.all([
        listModelVersions(session.access_token),
        listTrainingJobs(session.access_token),
      ]);
      setVersions(vData.items);
      setTrainingJobs(tData.items);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load model registry");
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleFileUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const baseName = file.name.replace(/\.[^/.]+$/, "");
    if (!versionTag) {
      setVersionTag(`v-${baseName.toLowerCase().replace(/[^a-z0-9]/g, "-")}`);
    }
    setArtifactUri(`s3://graphrec-models/uploads/${file.name}`);
  }

  async function handleUploadModel(e: React.FormEvent) {
    e.preventDefault();
    if (!session || !versionTag.trim()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await registerModelVersion(session.access_token, {
        version_tag: versionTag.trim(),
        model_type: modelType,
        metrics: {
          recall_at_10: parseFloat(recall) || 0.8,
          ndcg_at_10: parseFloat(ndcg) || 0.7,
          training_loss: parseFloat(loss) || 0.2,
        },
        artifact_uri: artifactUri || `s3://graphrec-models/uploads/${versionTag}.bin`,
      });
      setVersionTag("");
      setArtifactUri("");
      setActiveTab("registry");
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Model upload failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleLaunchTraining() {
    if (!session) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await createTrainingJob(session.access_token, {
        model_type: modelType,
        configuration: { random_seed: 42, epochs: 20 },
      });
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to launch training job");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleActivate(id: string) {
    if (!session) return;
    try {
      await activateModelVersion(session.access_token, id);
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Activation failed");
    }
  }

  async function handleRollback(id: string) {
    if (!session) return;
    try {
      await rollbackModel(session.access_token, id);
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Rollback failed");
    }
  }

  async function handleArchive(id: string) {
    if (!session) return;
    try {
      await archiveModelVersion(session.access_token, id);
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Archive failed");
    }
  }

  if (!session) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in to manage model versions and training jobs.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fapp%2Fmodels">
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
          <p className="eyebrow">ML Engineering / Model Registry</p>
          <h1>Model Upload & Registry</h1>
          <p className="lede compact">
            Upload pre-trained model artifacts, register model versions, evaluate metrics, and launch training jobs.
          </p>
        </div>
        <div className="page-actions">
          <button className="button secondary" type="button" onClick={() => void loadData()} disabled={isRefreshing}>
            {isRefreshing ? "Refreshing…" : "Refresh Registry"}
          </button>
        </div>
      </section>

      {/* Tabs Header */}
      <div className="page-actions" style={{ marginBottom: "1.5rem" }}>
        <button
          className={`button ${activeTab === "registry" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("registry")}
        >
          Model Versions Registry ({versions.length})
        </button>
        <button
          className={`button ${activeTab === "upload" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("upload")}
        >
          Upload Model Artifact
        </button>
        <button
          className={`button ${activeTab === "training" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("training")}
        >
          Training Jobs ({trainingJobs.length})
        </button>
      </div>

      {error ? (
        <div className="error-panel" role="alert" style={{ marginBottom: "1.5rem" }}>
          <strong>Model Error</strong>
          <p>{error}</p>
        </div>
      ) : null}

      {/* Upload Tab */}
      {activeTab === "upload" ? (
        <section className="auth-card" style={{ maxWidth: "none", margin: "0 0 2rem" }}>
          <h2>Upload Model Artifact or Config</h2>
          <p className="form-note">
            Upload model weights (.bin, .pth, .onnx) or specify model metadata for registration.
          </p>

          <form onSubmit={(e) => void handleUploadModel(e)}>
            <label htmlFor="model-file">Select Model File</label>
            <input
              id="model-file"
              type="file"
              onChange={(e) => void handleFileUpload(e)}
              style={{ minHeight: "auto", padding: "0.5rem" }}
            />

            <label htmlFor="version-tag">Version Tag</label>
            <input
              id="version-tag"
              value={versionTag}
              onChange={(e) => setVersionTag(e.target.value)}
              placeholder="e.g. v2026.08-dgsr-alpha"
              required
            />

            <label htmlFor="model-type">Model Algorithm / Architecture</label>
            <input
              id="model-type"
              value={modelType}
              onChange={(e) => setModelType(e.target.value)}
              placeholder="simplified_dgsr"
              required
            />

            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1rem" }}>
              <div>
                <label htmlFor="metric-recall">Recall@10</label>
                <input
                  id="metric-recall"
                  type="number"
                  step="0.01"
                  value={recall}
                  onChange={(e) => setRecall(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="metric-ndcg">NDCG@10</label>
                <input
                  id="metric-ndcg"
                  type="number"
                  step="0.01"
                  value={ndcg}
                  onChange={(e) => setNdcg(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="metric-loss">Training Loss</label>
                <input
                  id="metric-loss"
                  type="number"
                  step="0.01"
                  value={loss}
                  onChange={(e) => setLoss(e.target.value)}
                />
              </div>
            </div>

            <label htmlFor="artifact-uri">Artifact Storage URI</label>
            <input
              id="artifact-uri"
              value={artifactUri}
              onChange={(e) => setArtifactUri(e.target.value)}
              placeholder="s3://graphrec-models/tenant-id/model.bin"
            />

            <button className="button primary" type="submit" disabled={isSubmitting || !versionTag.trim()}>
              {isSubmitting ? "Registering Model…" : "Register Model Version"}
            </button>
          </form>
        </section>
      ) : null}

      {/* Model Registry List Tab */}
      {activeTab === "registry" ? (
        <section className="limits-card">
          <div className="limits-card-heading">
            <p className="eyebrow">Model Version History</p>
            <h2>Registered Versions</h2>
          </div>
          {versions.length === 0 ? (
            <div className="empty-keys" role="status" style={{ marginTop: "1rem" }}>
              <h2>No registered model versions</h2>
              <p>Upload a model artifact or run a training job to register your first model.</p>
            </div>
          ) : (
            <div className="key-list">
              {versions.map((ver) => (
                <article className="key-card" key={ver.id}>
                  <div className="key-card-title">
                    <div>
                      <h2>{ver.version_tag}</h2>
                      <code>{ver.model_type}</code>
                    </div>
                    <span
                      className={`key-status ${
                        ver.status === "active"
                          ? "key-active"
                          : ver.status === "eligible"
                          ? "key-grace"
                          : ver.status === "retired"
                          ? "key-expired"
                          : "key-revoked"
                      }`}
                    >
                      {ver.status}
                    </span>
                  </div>
                  <dl className="key-metadata">
                    <div>
                      <dt>Recall@10</dt>
                      <dd>{ver.metrics?.recall_at_10 ?? "N/A"}</dd>
                    </div>
                    <div>
                      <dt>NDCG@10</dt>
                      <dd>{ver.metrics?.ndcg_at_10 ?? "N/A"}</dd>
                    </div>
                    <div>
                      <dt>Training Loss</dt>
                      <dd>{ver.metrics?.training_loss ?? "N/A"}</dd>
                    </div>
                  </dl>
                  <div className="key-actions">
                    {ver.status !== "active" && ver.status !== "archived" ? (
                      <button className="button primary compact-btn" onClick={() => void handleActivate(ver.id)}>
                        Activate Version
                      </button>
                    ) : null}
                    {ver.status === "retired" ? (
                      <button className="button secondary compact-btn" onClick={() => void handleRollback(ver.id)}>
                        Roll Back To This
                      </button>
                    ) : null}
                    {ver.status !== "active" && ver.status !== "archived" ? (
                      <button className="button danger compact-btn" onClick={() => void handleArchive(ver.id)}>
                        Archive
                      </button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {/* Training Jobs Tab */}
      {activeTab === "training" ? (
        <section className="limits-card">
          <div className="limits-card-heading" style={{ flexWrap: "wrap" }}>
            <div>
              <p className="eyebrow">Snapshot Model Training</p>
              <h2>Training Runs</h2>
            </div>
            <button className="button primary compact-btn" onClick={() => void handleLaunchTraining()} disabled={isSubmitting}>
              {isSubmitting ? "Launching…" : "Launch Snapshot Training"}
            </button>
          </div>
          {trainingJobs.length === 0 ? (
            <div className="empty-keys" role="status" style={{ marginTop: "1rem" }}>
              <h2>No training jobs executed</h2>
              <p>Click "Launch Snapshot Training" to trigger a tenant model training run.</p>
            </div>
          ) : (
            <div className="key-list">
              {trainingJobs.map((job) => (
                <article className="key-card" key={job.id}>
                  <div className="key-card-title">
                    <div>
                      <h2>Training Job: {job.model_type}</h2>
                      <code>ID: {job.id.substring(0, 8)}…</code>
                    </div>
                    <span className="key-status key-active">{job.status}</span>
                  </div>
                  <dl className="key-metadata">
                    <div>
                      <dt>Created At</dt>
                      <dd>{new Date(job.created_at).toLocaleString()}</dd>
                    </div>
                    <div>
                      <dt>Config</dt>
                      <dd>{JSON.stringify(job.configuration)}</dd>
                    </div>
                    <div>
                      <dt>Result Model Version</dt>
                      <dd>{job.model_version_id ? job.model_version_id.substring(0, 8) : "N/A"}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </main>
  );
}
