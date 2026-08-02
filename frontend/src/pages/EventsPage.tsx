import { useEffect, useState } from "react";
import { getEventBatch } from "../api/events";
import type { EventBatchResponse } from "../api/types";
import { getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { SpaLink } from "../components/SpaLink";

export function EventsPage() {
  const session = getAuthSession();
  const [batches, setBatches] = useState<EventBatchResponse[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      void loadEvents();
    }
  }, [session]);

  async function loadEvents() {
    if (!session) return;
    setIsLoading(true);
    try {
      const res = await fetch("/v1/events/batches", {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setBatches(data);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load event batches");
    } finally {
      setIsLoading(false);
    }
  }

  if (!session) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in to inspect customer event ingestion.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fapp%2Fevents%2Fbatches">
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
          <p className="eyebrow">Events / Batches</p>
          <h1>Customer Event Batches</h1>
          <p className="lede compact">Inspect real-time customer event ingestion and processing counters.</p>
        </div>
        <div className="page-actions">
          <SpaLink className="button primary" href="/app/data">
            Batch Ingestion Tool
          </SpaLink>
          <button className="button secondary" type="button" onClick={() => void loadEvents()} disabled={isLoading}>
            {isLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </section>

      {error ? (
        <div className="error-panel" role="alert" style={{ marginBottom: "1.5rem" }}>
          <strong>Event Error</strong>
          <p>{error}</p>
        </div>
      ) : null}

      <section className="limits-card">
        <div className="limits-card-heading">
          <p className="eyebrow">Batch History</p>
          <h2>Processed Event Batches ({batches.length})</h2>
        </div>
        {batches.length === 0 ? (
          <div className="empty-keys" role="status" style={{ marginTop: "1rem" }}>
            <h2>No event batches ingested</h2>
            <p>Use Data Upload to ingest customer interaction batches.</p>
          </div>
        ) : (
          <div className="key-list">
            {batches.map((b) => (
              <article className="key-card" key={b.id}>
                <div className="key-card-title">
                  <div>
                    <h2>Batch {b.id.substring(0, 8)}…</h2>
                    <code>{new Date(b.created_at).toLocaleString()}</code>
                  </div>
                  <span className="key-status key-active">{b.status}</span>
                </div>
                <dl className="key-metadata">
                  <div>
                    <dt>Accepted</dt>
                    <dd>{b.accepted_count}</dd>
                  </div>
                  <div>
                    <dt>Duplicates</dt>
                    <dd>{b.duplicate_count}</dd>
                  </div>
                  <div>
                    <dt>Rejected</dt>
                    <dd>{b.rejected_count}</dd>
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
