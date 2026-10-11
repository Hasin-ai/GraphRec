import { useEffect, useState } from "react";
import { api, isUnavailable } from "../api";
import { DEFAULT_DIVERSITY, strategyDetail, strategyLabel, useDemo } from "../demo";
import type { Recs, Unavailable } from "../types";
import { FilmTile } from "./FilmTile";

/** Demo control: tune GraphRec's MMR diversity live. */
/** Highest slider value: at 1.0 MMR ignores relevance entirely, which only makes a list look random. */
const MAX_DIVERSITY = 0.8;

function ServingControls({ applied }: { applied: boolean }) {
  const { serving, appliedServing, setServing } = useDemo();
  const [draft, setDraft] = useState(serving.diversity);
  useEffect(() => setDraft(serving.diversity), [serving.diversity]);
  // Commit once the slider has been still for a moment, so a drag or a run of arrow
  // keys asks GraphRec once, for the value the viewer settled on.
  useEffect(() => {
    if (Math.abs(draft - serving.diversity) < 1e-9) return;
    const timer = window.setTimeout(() => { void setServing({ diversity: draft }); }, 350);
    return () => window.clearTimeout(timer);
  }, [draft, serving.diversity, setServing]);
  return (
    <div className="serving-controls">
      <label className="diversity" title="MMR: 0 ranks by relevance only; higher values trade relevance for variety">
        <span>Diversity <b>{draft.toFixed(2)}</b></span>
        <input type="range" min={0} max={MAX_DIVERSITY} step={0.05} value={Math.min(draft, MAX_DIVERSITY)} aria-label="Diversity"
          onChange={(e) => setDraft(Math.round(Number(e.target.value) * 100) / 100)} />
        {Math.abs(draft - DEFAULT_DIVERSITY) > 1e-9 && (
          <button className="link" onClick={() => setDraft(DEFAULT_DIVERSITY)}>reset</button>
        )}
      </label>
      {applied && Math.abs(draft - appliedServing.diversity) > 1e-9 && <span className="muted small">
        Press “Update picks” to apply.</span>}
      {!applied && <span className="muted small" title="Diversity re-ranks the model's candidates; a popular list has none to spread">
        Not applied to popular picks — watch a film first.</span>}
    </div>
  );
}

export function Shelf({ recs, loading, onUpdate, pending, emptyHint }: {
  recs: Recs | Unavailable | null; loading: boolean; onUpdate?: () => void; pending?: number; emptyHint?: string;
}) {
  const { setInsight, insightOpen, notify, watchedIds, serving, appliedServing } = useDemo();
  const settingsChanged = Math.abs(serving.diversity - appliedServing.diversity) > 1e-9;
  if (!recs) {
    return (
      <section className="shelf" aria-busy="true">
        <div className="shelf-skeleton"><div className="row">{Array.from({ length: 7 }, (_, i) => <div key={i} className="tile-ghost" />)}</div></div>
      </section>
    );
  }
  if (isUnavailable(recs)) {
    return (
      <section className="shelf">
        <div className="shelf-error">
          <strong>Recommendations are not available right now.</strong> Browsing still works.
          <small>{recs.reason}{recs.correlationId ? ` · ref ${recs.correlationId}` : ""}</small>
          {onUpdate && <button className="btn small" onClick={onUpdate}>Try again</button>}
        </div>
      </section>
    );
  }
  const s = recs.trace.strategy;
  return (
    <section className={`shelf ${loading ? "is-loading" : ""}`} aria-busy={loading}>
      <header className="shelf-head">
        <div>
          <h2>{recs.title}</h2>
          <div className="shelf-sub">
            <button className={`pill strategy ${s}`} title={strategyDetail(s)} onClick={() => setInsight(true, "status")}>{recs.shelf === "more_like" && s !== "personalized" && !s.includes("fallback") ? "Similar films" : strategyLabel(s)}</button>
            {insightOpen && <button className="pill quiet" onClick={() => setInsight(true, "trace")}>{recs.trace.latencyMs} ms · trace</button>}
            {insightOpen && recs.diff.hasPrevious && <button className="pill change" onClick={() => setInsight(true, "changes")}>{recs.diff.summary}</button>}
            {insightOpen && recs.trace.explain && <button className="pill quiet" onClick={() => setInsight(true, "pipeline")}>pipeline</button>}
          </div>
          {onUpdate && <ServingControls applied={!recs.trace.fallbackUsed} />}
        </div>
        {onUpdate && (
          <button className={`btn primary ${pending || settingsChanged ? "has-pending" : ""}`} onClick={onUpdate} disabled={loading} title="Ask GraphRec for a fresh list using everything you've watched">
            {loading ? "Updating…" : "Update picks"}{pending ? <span className="count" aria-label={`${pending} new since last update`}>{pending}</span> : null}
          </button>
        )}
      </header>
      {recs.items.length === 0
        ? <p className="muted">{emptyHint ?? "Nothing to suggest yet."}</p>
        : <div className="row">
            {recs.items.map((item) => (
              <FilmTile key={item.id} film={item} ranked={item} requestId={recs.trace.requestId} watched={watchedIds.has(item.id)}
                onOpen={() => api.click(recs.trace.requestId, item.id, item.position).catch(() => notify("Click feedback failed"))} />
            ))}
          </div>}
    </section>
  );
}
