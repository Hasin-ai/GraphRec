import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, isUnavailable } from "../api";
import { strategyDetail, useDemo, type Tab } from "../demo";
import type { Sequence, Status } from "../types";
import { Poster } from "./FilmTile";

const TABS: { key: Tab; label: string }[] = [
  { key: "sequence", label: "Sequence" },
  { key: "changes", label: "Changes" },
  { key: "trace", label: "Trace" },
  { key: "status", label: "Status" },
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
        {tab === "trace" && <TraceTab />}
        {tab === "status" && <StatusTab />}
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

function TraceTab() {
  const { lastTrace } = useDemo();
  if (!lastTrace) return <p className="muted">No request yet.</p>;
  const t = lastTrace.trace;
  const request = { endpoint: t.request.endpoint, user_id: t.request.userId, top_n: t.request.topN,
    "context.recent_product_ids": t.request.recentProductIds, exclude_product_ids: t.request.excludeCount };
  const response = { request_id: t.requestId, model_version_id: t.modelVersionId, strategy: t.strategy,
    fallback_used: t.fallbackUsed, fallback_tier: t.fallbackTier, applied_rules: t.appliedRules,
    items: lastTrace.items.map((i) => ({ position: i.position, external_product_id: i.id, title: i.title })) };
  return (
    <>
      <p className="explain">The last request this storefront sent through the Python SDK, and GraphRec's answer. The API returns ranks only; no scores are shown because none are returned.</p>
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
