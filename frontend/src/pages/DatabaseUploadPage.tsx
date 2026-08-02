import { useEffect, useState } from "react";
import { bulkUpsertProducts, disableProduct, listProducts } from "../api/products";
import { submitEventBatch } from "../api/events";
import {
  createDatasetSnapshot,
  listDatasetSnapshots,
  uploadDatasetFile,
  type DatasetSnapshotResource,
} from "../api/datasets";
import type { ProductBulkUpsertResponse, ProductResource } from "../api/types";
import { getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";

export function DatabaseUploadPage() {
  const session = getAuthSession();
  const [activeTab, setActiveTab] = useState<"products" | "events" | "snapshots">("products");
  const [jsonInput, setJsonInput] = useState("");
  const [products, setProducts] = useState<ProductResource[]>([]);
  const [snapshots, setSnapshots] = useState<DatasetSnapshotResource[]>([]);
  const [lastResult, setLastResult] = useState<ProductBulkUpsertResponse | null>(null);
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
      const [pData, sData] = await Promise.all([
        listProducts(session.access_token),
        listDatasetSnapshots(session.access_token),
      ]);
      setProducts(pData.items);
      setSnapshots(sData.items);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load tenant dataset information");
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleFileUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !session) return;

    if (activeTab === "snapshots") {
      setIsSubmitting(true);
      setError(null);
      try {
        const res = await uploadDatasetFile(session.access_token, file);
        setSnapshots((prev) => [res.dataset_snapshot, ...prev]);
        setLastResult({
          accepted_count: res.accepted_events + res.accepted_products,
          created_count: res.accepted_products,
          updated_count: 0,
          skipped_count: 0,
          rejected_count: 0,
          failures: [],
        });
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "Dataset file upload failed");
      } finally {
        setIsSubmitting(false);
      }
      return;
    }

    const text = await file.text();
    setJsonInput(text);
  }

  async function handleIngestProducts() {
    if (!session || !jsonInput.trim()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      let parsed = JSON.parse(jsonInput);
      if (Array.isArray(parsed)) {
        parsed = { products: parsed };
      }
      const idempotencyKey = crypto.randomUUID();
      const res = await bulkUpsertProducts(session.access_token, parsed, idempotencyKey);
      setLastResult(res);
      setJsonInput("");
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Invalid JSON format or ingestion failure");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleIngestEvents() {
    if (!session || !jsonInput.trim()) return;
    setIsSubmitting(true);
    setError(null);
    try {
      let parsed = JSON.parse(jsonInput);
      if (Array.isArray(parsed)) {
        parsed = { events: parsed };
      }
      const res = await submitEventBatch(session.access_token, parsed);
      setLastResult({
        accepted_count: res.accepted_count,
        created_count: res.accepted_count,
        updated_count: 0,
        skipped_count: res.duplicate_count,
        rejected_count: res.rejected_count,
        failures: [],
      });
      setJsonInput("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Invalid JSON format or event batch failure");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleGenerateSnapshot() {
    if (!session) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const snap = await createDatasetSnapshot(session.access_token);
      setSnapshots((prev) => [snap, ...prev]);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to generate dataset snapshot");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleDisable(externalId: string) {
    if (!session) return;
    try {
      await disableProduct(session.access_token, externalId);
      await loadData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to disable product");
    }
  }

  if (!session) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in to manage database upload & data ingestion.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fapp%2Fdata">
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
          <p className="eyebrow">Data & Ingestion / Database Upload</p>
          <h1>Database Upload & Dataset Preparation</h1>
          <p className="lede compact">
            Upload dataset exports, bulk synchronize product catalogs, and generate reproducible dataset snapshots for training.
          </p>
        </div>
        <div className="page-actions">
          <button className="button secondary" type="button" onClick={() => void loadData()} disabled={isRefreshing}>
            {isRefreshing ? "Refreshing…" : "Refresh Catalog"}
          </button>
        </div>
      </section>

      {/* Tabs Header */}
      <div className="page-actions" style={{ marginBottom: "1.5rem" }}>
        <button
          className={`button ${activeTab === "products" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("products")}
        >
          Product Catalog Upload
        </button>
        <button
          className={`button ${activeTab === "events" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("events")}
        >
          Customer Events Ingestion
        </button>
        <button
          className={`button ${activeTab === "snapshots" ? "primary" : "secondary"}`}
          onClick={() => setActiveTab("snapshots")}
        >
          Dataset Snapshots for Training ({snapshots.length})
        </button>
      </div>

      {error ? (
        <div className="error-panel" role="alert" style={{ marginBottom: "1.5rem" }}>
          <strong>Ingestion Error</strong>
          <p>{error}</p>
        </div>
      ) : null}

      {/* Ingestion Panel */}
      {activeTab !== "snapshots" ? (
        <section className="auth-card" style={{ maxWidth: "none", margin: "0 0 2rem" }}>
          <h2>{activeTab === "products" ? "Bulk Upload Product Database" : "Submit Customer Events Batch"}</h2>
          <p className="form-note">
            Upload a JSON file or paste a formatted JSON payload.
          </p>

          <div style={{ margin: "1rem 0" }}>
            <label htmlFor="file-upload">Choose JSON File export</label>
            <input
              id="file-upload"
              type="file"
              accept=".json,.csv"
              onChange={(e) => void handleFileUpload(e)}
              style={{ minHeight: "auto", padding: "0.5rem" }}
            />
          </div>

          <label htmlFor="json-editor">JSON Payload Input</label>
          <textarea
            id="json-editor"
            value={jsonInput}
            onChange={(e) => setJsonInput(e.target.value)}
            rows={8}
            placeholder={
              activeTab === "products"
                ? JSON.stringify(
                    [
                      {
                        external_id: "sku-101",
                        title: "GraphRec Pro Shirt",
                        price: 29.99,
                        category: "Apparel",
                        is_active: true,
                      },
                    ],
                    null,
                    2,
                  )
                : JSON.stringify(
                    [
                      {
                        event_id: "evt-901",
                        event_type: "click",
                        user_id: "user-44",
                        external_product_id: "sku-101",
                      },
                    ],
                    null,
                    2,
                  )
            }
            style={{
              width: "100%",
              fontFamily: "monospace",
              borderRadius: "0.8rem",
              padding: "0.85rem",
              border: "1px solid var(--line)",
            }}
          />

          <div style={{ marginTop: "1.25rem" }}>
            {activeTab === "products" ? (
              <button
                className="button primary"
                onClick={() => void handleIngestProducts()}
                disabled={isSubmitting || !jsonInput.trim()}
              >
                {isSubmitting ? "Ingesting Products…" : "Upload & Sync Products"}
              </button>
            ) : (
              <button
                className="button primary"
                onClick={() => void handleIngestEvents()}
                disabled={isSubmitting || !jsonInput.trim()}
              >
                {isSubmitting ? "Ingesting Events…" : "Submit Event Batch"}
              </button>
            )}
          </div>
        </section>
      ) : (
        <section className="auth-card" style={{ maxWidth: "none", margin: "0 0 2rem" }}>
          <h2>Training Dataset Upload & Snapshot Management</h2>
          <p className="form-note">
            Upload raw interaction dataset files directly or generate an immutable dataset snapshot from current tenant behavior logs.
          </p>

          <div style={{ margin: "1rem 0" }}>
            <label htmlFor="dataset-file-upload">Upload Dataset File (.json, .csv, .parquet)</label>
            <input
              id="dataset-file-upload"
              type="file"
              accept=".json,.csv,.parquet"
              onChange={(e) => void handleFileUpload(e)}
              style={{ minHeight: "auto", padding: "0.5rem" }}
            />
          </div>

          <div style={{ marginTop: "1.25rem" }}>
            <button
              className="button primary"
              onClick={() => void handleGenerateSnapshot()}
              disabled={isSubmitting}
            >
              {isSubmitting ? "Generating Snapshot…" : "Generate Dataset Snapshot from Current Data"}
            </button>
          </div>
        </section>
      )}

      {/* Ingestion Results Feedback Card */}
      {lastResult ? (
        <section className="plan-summary" style={{ marginBottom: "2rem" }}>
          <div>
            <p className="eyebrow">Recent Ingestion Result</p>
            <h2>Bulk Sync Status</h2>
          </div>
          <dl>
            <div>
              <dt>Accepted</dt>
              <dd><span className="status-badge">{lastResult.accepted_count}</span></dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{lastResult.created_count}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{lastResult.updated_count}</dd>
            </div>
            <div>
              <dt>Skipped / Duplicates</dt>
              <dd>{lastResult.skipped_count}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      {/* Snapshots Table */}
      {activeTab === "snapshots" ? (
        <section className="limits-card">
          <div className="limits-card-heading">
            <p className="eyebrow">Immutable Snapshots</p>
            <h2>Available Dataset Snapshots ({snapshots.length})</h2>
          </div>
          {snapshots.length === 0 ? (
            <div className="empty-keys" role="status" style={{ marginTop: "1rem" }}>
              <h2>No dataset snapshots created</h2>
              <p>Click "Generate Dataset Snapshot" or upload a dataset file to prepare training data.</p>
            </div>
          ) : (
            <div className="key-list">
              {snapshots.map((snap) => (
                <article className="key-card" key={snap.id}>
                  <div className="key-card-title">
                    <div>
                      <h2>Snapshot: {snap.id.substring(0, 8)}…</h2>
                      <code>Cutoff: {new Date(snap.cutoff_at).toLocaleString()}</code>
                    </div>
                    <span className="key-status key-active">Immutable</span>
                  </div>
                  <dl className="key-metadata">
                    <div>
                      <dt>Events Count</dt>
                      <dd>{snap.event_count}</dd>
                    </div>
                    <div>
                      <dt>Products Count</dt>
                      <dd>{snap.product_count}</dd>
                    </div>
                    <div>
                      <dt>Unique Users</dt>
                      <dd>{snap.user_count}</dd>
                    </div>
                    <div>
                      <dt>Artifact URI</dt>
                      <dd><code>{snap.artifact_uri}</code></dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {/* Catalog Table */}
      {activeTab === "products" ? (
        <section className="limits-card">
          <div className="limits-card-heading">
            <p className="eyebrow">Tenant Product Catalog</p>
            <h2>Uploaded Products ({products.length})</h2>
          </div>
          {products.length === 0 ? (
            <div className="empty-keys" role="status" style={{ marginTop: "1rem" }}>
              <h2>No products in catalog</h2>
              <p>Upload a product database JSON payload above to synchronize products.</p>
            </div>
          ) : (
            <div className="key-list">
              {products.map((prod) => (
                <article className="key-card" key={prod.id}>
                  <div className="key-card-title">
                    <div>
                      <h2>{prod.title}</h2>
                      <code>{prod.external_id}</code>
                    </div>
                    <span className={`key-status ${prod.is_active ? "key-active" : "key-revoked"}`}>
                      {prod.is_active ? "Active" : "Disabled"}
                    </span>
                  </div>
                  <dl className="key-metadata">
                    <div>
                      <dt>Price</dt>
                      <dd>${prod.price}</dd>
                    </div>
                    <div>
                      <dt>Category</dt>
                      <dd>{prod.category || "Unassigned"}</dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>{prod.availability_status}</dd>
                    </div>
                  </dl>
                  {prod.is_active ? (
                    <div className="key-actions">
                      <button
                        className="button danger compact-btn"
                        onClick={() => void handleDisable(prod.external_id)}
                      >
                        Disable Product
                      </button>
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </main>
  );
}
