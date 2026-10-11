import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, isUnavailable } from "../api";
import { strategyDetail, useDemo, type Tab } from "../demo";
import type { ProofReport, Sequence, Status } from "../types";
import { Poster } from "./FilmTile";

const TABS: { key: Tab; label: string }[] = [
  { key: "sequence", label: "Sequence" },
  { key: "changes", label: "Changes" },
  { key: "pipeline", label: "Pipeline" },
  { key: "trace", label: "Trace" },
  { key: "status", label: "Status" },
  { key: "proof", label: "Proof" },
];

export function Insight() {
  const { insightOpen, tab, setInsight } = useDemo();
  if (!insightOpen) return null;
  return (
    <aside className="insight" aria-label="GraphRec insight">
      <div className="insight-head">
        <strong>What GraphRec did</strong>
        <button className="icon" onClick={() => setInsight(false)} aria-label="Close">×</button>
      </div>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} className={tab === t.key ? "on" : ""} onClick={() => setInsight(true, t.key)}>{t.label}</button>
        ))}
      </div>
      <div className="insight-body">
        {tab === "sequence" && <SequenceTab />}
        {tab === "changes" && <ChangesTab />}
        {tab === "pipeline" && <PipelineTab />}
        {tab === "trace" && <TraceTab />}
        {tab === "status" && <StatusTab />}
        {tab === "proof" && <ProofTab />}
      </div>
    </aside>
  );
}

function SequenceTab() {
  const { version, receipts, replay, autoRefresh, setAutoRefresh, session } = useDemo();
  const [seq, setSeq] = useState<Sequence | null>(null);
  useEffect(() => { api.sequence().then(setSeq).catch(() => setSeq(null)); }, [version, session?.persona.key]);
  return (
    <>
      <p className="explain">
        {seq?.sessionOnly
          ? "Anonymous: this session's films are sent with each request as recent_product_ids."
          : "DGSR builds this shopper's subgraph from their last 20 interactions. Each new event enters on the right and pushes the oldest out."}
      </p>
      {seq && (
        <>
          <div className="seq-meta">
            <span><b>{seq.items.filter((i) => i.inWindow).length}</b> / {seq.window} in window</span>
            <span>{seq.total} events total</span>
            <span className="live-key">{seq.liveCount} live</span>
          </div>
          {seq.items.length === 0 && <p className="muted">No interactions yet. Watch a film.</p>}
          <ol className="seq">
            {seq.items.map((i, n) => (
              <li key={`${i.film.id}-${i.time}-${n}`} className={`${i.origin} ${i.evicted ? "evicted" : ""}`} title={`${i.film.title} · ${new Date(i.time * 1000).toLocaleDateString()} · ${i.origin === "live" ? "live demo event" : "training history"}`}>
                <Link to={`/film/${i.film.id}`}><Poster film={i.film} /></Link>
                <span>{i.film.title}</span>
              </li>
            ))}
          </ol>
          <div className="legend"><span className="sw training" /> training history <span className="sw live" /> live demo event <span className="sw evicted" /> pushed out</div>
        </>
      )}
      <h4>Event receipts</h4>
      {receipts.length === 0 ? <p className="muted">Nothing sent yet this visit.</p> : (
        <ul className="receipts">
          {receipts.slice(0, 6).map((r, n) => (
            <li key={`${r.eventId}-${n}`} className={r.duplicate ? "dup" : "ok"}>
              <span className="tag">{r.duplicate ? "duplicate" : "accepted"}</span> <code>{r.eventType}</code> · film {r.filmId} · <code>{r.eventId}</code> · {r.latencyMs} ms
            </li>
          ))}
        </ul>
      )}
      <div className="row-actions">
        <button className="btn small" onClick={replay} title="Send the last event again with the same event id">Replay last event</button>
        <label className="toggle"><input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} /> Auto-update after each event</label>
      </div>
    </>
  );
}

function ChangesTab() {
  const { home } = useDemo();
  if (!home || isUnavailable(home)) return <p className="muted">No recommendation list yet.</p>;
  const d = home.diff;
  return (
    <>
      <p className="explain">Compared with the previous “{home.title}” list shown to this shopper. Weights are unchanged; only the input history changed.</p>
      <div className="summary">{d.hasPrevious ? d.summary : "First list for this shopper. Watch a film, then press Update recommendations."}</div>
      <table className="diff">
        <thead><tr><th>#</th><th>Film</th><th>Before</th></tr></thead>
        <tbody>
          {home.items.map((i) => (
            <tr key={i.id} className={i.change}>
              <td>{i.position}</td>
              <td>{i.title}<small>{i.genres.slice(0, 3).join(" · ")}</small></td>
              <td>{i.change === "new" ? "new" : i.previousPosition ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.left.length > 0 && (<><h4>Left the list</h4><div className="chips">{d.left.map((f) => <span key={f.id} className="chip static strike">{f.title}</span>)}</div></>)}
    </>
  );
}

const STAGE_LABEL: Record<string, string> = {
  query: "Query", retrieval: "Retrieval", eligibility: "Eligibility", scoring: "Scoring", rerank: "Re-rank", guarantee: "Guarantee",
};
const SOURCE_LABEL: Record<string, string> = {
  dgsr_personalized: "DGSR personalized", session_neighbors: "Session neighbors",
  popular_in_category: "Popular in category", trending: "Trending", last_good: "Last good list",
};
const SOURCE_ORDER = ["dgsr_personalized", "session_neighbors", "popular_in_category", "trending"];
const SOURCE_HELP: Record<string, string> = {
  dgsr_personalized: "Qdrant ANN over the DGSR item table with the shopper's encoded history (in-process scoring if Qdrant is slow or down)",
  session_neighbors: "Films whose DGSR embeddings sit closest to the last films watched",
  popular_in_category: "Most watched recently in the genres of the films just watched",
  trending: "Most watched across the store recently",
};
const fmt = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : v.toFixed(d));

/** The glass-box funnel for the last request: stage counts and timings, sources, and the score of every candidate. */
function PipelineTab() {
  const { lastTrace } = useDemo();
  if (!lastTrace) return <p className="muted">No request yet.</p>;
  const x = lastTrace.trace.explain;
  if (!x) {
    return <p className="explain">This answer carried no pipeline trace.</p>;
  }
  const shown = new Map(lastTrace.items.map((i) => [i.id, i.position]));
  const counted = x.stages.filter((s) => s.name !== "query");
  const widest = Math.max(1, ...counted.map((s) => s.count));
  return (
    <>
      <p className="explain">
        How GraphRec built this list: four sources propose candidates, the catalogue removes anything unservable,
        each survivor gets one blended score, and MMR spreads the final picks. Total {fmt(x.total_ms, 1)} ms inside GraphRec.
      </p>
      <ol className="funnel" aria-label="Pipeline stages">
        {counted.map((s) => (
          <li key={s.name}>
            <span className="funnel-name">{STAGE_LABEL[s.name] ?? s.name}</span>
            <span className="funnel-bar"><span style={{ width: `${Math.max(4, (s.count / widest) * 100)}%` }} /></span>
            <span className="funnel-count">{s.count}</span>
            <span className="funnel-ms">{fmt(s.ms, 1)} ms</span>
          </li>
        ))}
      </ol>
      {Object.keys(x.sources).length === 0 && (
        <p className="explain">
          GraphRec knows nothing about this visitor yet, so no model source ran: the list is the tenant's
          recent popularity (fallback tier <code>{lastTrace.trace.fallbackTier}</code>). Watch a film to see the
          personalized sources take over.
        </p>
      )}
      {Object.keys(x.sources).length > 0 && <>
      <h4>Sources</h4>
      <table className="mini">
        <thead><tr><th>Source</th><th>Status</th><th>Found</th><th>ms</th></tr></thead>
        <tbody>
          {Object.entries(x.sources).sort(([a], [b]) => SOURCE_ORDER.indexOf(a) - SOURCE_ORDER.indexOf(b)).map(([name, s]) => (
            <tr key={name} title={SOURCE_HELP[name]}>
              <td>{SOURCE_LABEL[name] ?? name}</td>
              <td><span className={`status ${s.status.includes("error") || s.status.includes("timeout") || s.status.includes("unavailable") ? "warn" : "ok"}`}>{s.status.replace("->", " → ")}</span></td>
              <td>{s.count}</td><td>{fmt(s.ms, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h4>Scoring</h4>
      <p className="explain">
        final = {fmt(x.weights.model)} × DGSR percentile + {fmt(x.weights.popularity)} × popularity percentile
        + {fmt(x.weights.agreement)} × source agreement · MMR diversity {fmt(x.diversity)}
      </p>
      <div className="table-scroll">
        <table className="mini scores">
          <thead><tr><th>#</th><th>Film</th><th>Sources</th><th>DGSR</th><th>Pop.</th><th>Agree</th><th>Final</th><th>Shown</th></tr></thead>
          <tbody>
            {x.candidates.map((c) => {
              const pos = shown.get(c.external_product_id);
              return (
                <tr key={c.external_product_id} className={pos ? "picked" : ""}>
                  <td>{c.rank_before_rerank}</td>
                  <td>{c.title ?? c.external_product_id}{c.anchor_title ? <small> ← {c.anchor_title}</small> : null}</td>
                  <td>{c.sources.map((s) => <span key={s} className={`src ${s}`} title={SOURCE_LABEL[s] ?? s}>{(SOURCE_LABEL[s] ?? s).split(" ").map((w) => w[0]).join("")}</span>)}</td>
                  <td>{fmt(c.model_norm)}</td><td>{fmt(c.popularity_norm)}</td><td>{fmt(c.agreement)}</td><td><b>{fmt(c.final, 3)}</b></td>
                  <td>{pos ? `#${pos}` : ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">Rows are in relevance order before re-ranking; “Shown” is the final position after MMR and policy rules.</p>
      </>}
    </>
  );
}

function TraceTab() {
  const { lastTrace } = useDemo();
  if (!lastTrace) return <p className="muted">No request yet.</p>;
  const t = lastTrace.trace;
  const request = { endpoint: t.request.endpoint, user_id: t.request.userId, top_n: t.request.topN,
    "context.recent_product_ids": t.request.recentProductIds, exclude_product_ids: t.request.excludeCount };
  const response = { request_id: t.requestId, pipeline: t.pipeline, diversity: t.diversity, model_version_id: t.modelVersionId, strategy: t.strategy,
    fallback_used: t.fallbackUsed, fallback_tier: t.fallbackTier, applied_rules: t.appliedRules,
    items: lastTrace.items.map((i) => ({ position: i.position, external_product_id: i.id, title: i.title,
      ...(i.reason ? { reason: i.reason, sources: i.sources, score: i.score } : {}) })) };
  return (
    <>
      <p className="explain">The last request this storefront sent through the Python SDK, and GraphRec's answer. The Pipeline tab breaks the glass-box answer down by stage.</p>
      <div className="kv"><span>Strategy</span><b>{strategyDetail(t.strategy)}</b><span>Round trip</span><b>{t.latencyMs} ms</b></div>
      <h4>Request</h4><pre>{JSON.stringify(request, null, 2)}</pre>
      <h4>Response</h4><pre>{JSON.stringify(response, null, 2)}</pre>
    </>
  );
}

function StatusTab() {
  const { version, lastTrace } = useDemo();
  const [s, setS] = useState<Status | null>(null);
  useEffect(() => { api.status().then(setS).catch(() => setS(null)); }, [version]);
  if (!s) return <p className="muted">Loading…</p>;
  const c = s.modelCard;
  // What actually served the last list (it changes after a rollback or a fallback); the configured version may be stale.
  const servedBy = !lastTrace ? "no list yet" : lastTrace.trace.modelVersionId
    ? (lastTrace.trace.modelVersionId === s.modelVersionId && s.modelVersionTag ? s.modelVersionTag : lastTrace.trace.modelVersionId.slice(0, 8) + "…")
    : "popular fallback (no model)";
  return (
    <>
      <div className="kv">
        <span>Tenant</span><b>{s.tenant}</b>
        <span>GraphRec API</span><b className={s.graphrec === "ok" ? "good" : "bad"}>{s.graphrec}</b>
        <span>Set up with</span><b>{s.modelVersionTag || s.modelVersionId || "unknown"}</b>
        <span>Last list from</span><b>{servedBy}</b>
        {c ? <>
          <span>Model</span><b>DGSR · imported offline checkpoint</b>
          <span>Checkpoint</span><b><code>{c.checkpointSha256?.slice(0, 12)}…</code></b>
          <span>Trained on</span><b>{c.dataset} cohort · {c.users.toLocaleString()} users · {c.films.toLocaleString()} films · {c.interactions.toLocaleString()} ratings</b>
          <span>Config</span><b>dim {c.embeddingDim} · {c.layers} layers · window {c.recentItems} · {c.itemNeighborLimit} raters per film</b>
        </> : <>
          <span>Model</span><b>DGSR · trained by GraphRec on this store's own events</b>
        </>}
      </div>

      <h4>Deep Readiness Probes</h4>
      <div className="readiness-strip">
        {s.readiness && Object.entries(s.readiness).map(([k, v]) => (
          <span key={k} className="readiness-pill">
            <span className={`status-dot ${v === "ok" ? "ok" : "down"}`} />
            {k}: <b>{v}</b>
          </span>
        ))}
      </div>

      <h4>Telemetry Feedback Health</h4>
      {s.feedbackHealth && (
        <div className="telemetry-grid">
          {Object.entries(s.feedbackHealth).map(([kind, counts]) => (
            <div key={kind} className="telemetry-card">
              <span>{kind}</span>
              <b>{counts.success} ok</b>
              {counts.failure > 0 && <span className="err">{counts.failure} fail</span>}
            </div>
          ))}
        </div>
      )}

      <h4>Strategies you may see</h4>
      <ul className="plain">
        <li><b>Personalized</b> — a shopper from the training data; their trained embedding plus their history.</li>
        <li><b>Session</b> — no trained shopper; the history is encoded with the mean user vector (an approximation).</li>
        <li><b>Fallback</b> — nothing the model knows about this visitor; GraphRec's popular fallback.</li>
      </ul>
      {c ? <><h4>Offline quality (not measured by this demo)</h4>
      <table className="metrics">
        <tbody>
          {c.metrics.map((m) => (
            <tr key={m.protocol}>
              <td>{m.protocol}<small>{m.note}</small></td>
              <td>{m.recall10 !== undefined ? `Recall@10 ${(m.recall10 * 100).toFixed(2)}%` : `Hit@10 ${m.hit10} · NDCG@10 ${m.ndcg10}`}</td>
            </tr>
          ))}
        </tbody>
      </table></> : <p className="muted">This version's offline quality is on its model page in the GraphRec console.</p>}
      <h4>What this demo shows, and what it doesn't</h4>
      <ul className="plain">
        <li>Shows: events reach GraphRec, the active DGSR version re-ranks from the new history, without retraining.</li>
        <li>Doesn't show: recommendation quality, online learning, latency under load.</li>
      </ul>
    </>
  );
}

function ProofTab() {
  const [report, setReport] = useState<ProofReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    api.proofLatest().then(setReport).catch(() => setReport(null));
  }, []);

  const runBattery = async () => {
    setLoading(true);
    try {
      const rep = await api.proofRun("full");
      setReport(rep);
    } catch (err) {
      console.error("Proof battery run failed", err);
    } finally {
      setLoading(false);
    }
  };

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const summary = report?.summary;

  return (
    <>
      <p className="explain">
        Automated proof battery verifying all 19 core recommender capabilities (P1–P19) on demand against the live backend and active DGSR model.
      </p>

      <div className="row-actions" style={{ marginBottom: 14 }}>
        <button className="btn primary small" onClick={runBattery} disabled={loading}>
          {loading ? "Running proof battery…" : "Run Capability Battery (P1–P19)"}
        </button>
      </div>

      {summary && (
        <div className="proof-summary-card">
          <div className="head">
            <span style={{ fontWeight: 600 }}>Battery Result</span>
            <span className={`proof-badge ${summary.failed_checks === 0 ? "pass" : "fail"}`}>
              {summary.failed_checks === 0 ? "19/19 Verified" : `${summary.passed_checks}/${summary.total_checks} Degraded`}
            </span>
          </div>
          <div className="kv" style={{ fontSize: 12 }}>
            <span>Run ID</span><code>{summary.run_id}</code>
            <span>Profile</span><b>{summary.profile}</b>
            <span>Total Latency</span><b>{summary.total_duration_ms.toFixed(1)} ms</b>
            <span>Success Rate</span><b>{(summary.success_rate * 100).toFixed(1)}%</b>
          </div>
        </div>
      )}

      {report && (
        <>
          <h4>Capability Verifications (P1–P19)</h4>
          <table className="proof-table">
            <thead>
              <tr>
                <th style={{ width: 34 }}>ID</th>
                <th>Capability</th>
                <th style={{ width: 54 }}>Status</th>
                <th style={{ width: 55, textAlign: "right" }}>ms</th>
              </tr>
            </thead>
            <tbody>
              {report.checks.map((chk) => {
                const isOpen = expanded.has(chk.id);
                return (
                  <tr key={chk.id} className="clickable" onClick={() => toggleExpand(chk.id)}>
                    <td colSpan={4} style={{ padding: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 4px" }}>
                        <span style={{ fontWeight: 600, width: 34 }}>{chk.id}</span>
                        <div style={{ flex: 1, padding: "0 6px" }}>
                          <div>{chk.name}</div>
                          {chk.detail && <small style={{ color: "var(--ink-2)", display: "block" }}>{chk.detail}</small>}
                        </div>
                        <span className={`proof-badge ${chk.passed ? "pass" : "fail"}`} style={{ marginRight: 8 }}>
                          {chk.passed ? "PASS" : "FAIL"}
                        </span>
                        <span style={{ width: 50, textAlign: "right", color: "var(--ink-2)", fontSize: 11 }}>
                          {chk.duration_ms.toFixed(1)}
                        </span>
                      </div>
                      {isOpen && (
                        <div style={{ padding: "0 8px 8px" }}>
                          <pre className="proof-evidence-box">
                            {JSON.stringify(chk.evidence, null, 2)}
                          </pre>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}

      {!report && !loading && (
        <p className="muted" style={{ marginTop: 24, textAlign: "center" }}>
          No proof battery has been executed yet. Click above to run verification.
        </p>
      )}
    </>
  );
}
