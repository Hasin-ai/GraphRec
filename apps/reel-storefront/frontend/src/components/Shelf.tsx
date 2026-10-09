import { useEffect, useState } from "react";
import { api, isUnavailable } from "../api";
import { DEFAULT_DIVERSITY, strategyDetail, strategyLabel, useDemo } from "../demo";
import type { Recs, Unavailable } from "../types";
import { FilmTile } from "./FilmTile";

/** Demo control: tune GraphRec's MMR diversity live. */
function ServingControls() {
  const { serving, setServing, homeLoading } = useDemo();
  const [draft, setDraft] = useState(serving.diversity);
  useEffect(() => setDraft(serving.diversity), [serving.diversity]);
  return (
    <div className="serving-controls">
      <label className="diversity" title="MMR: 0 ranks by relevance only; higher values trade relevance for variety">
        <span>Diversity <b>{draft.toFixed(2)}</b></span>
        <input type="range" min={0} max={1} step={0.05} value={draft} disabled={homeLoading}
          onChange={(e) => setDraft(Number(e.target.value))}
          onPointerUp={() => draft !== serving.diversity && setServing({ diversity: draft })}
          onKeyUp={() => draft !== serving.diversity && setServing({ diversity: draft })} />
        {draft !== DEFAULT_DIVERSITY && <button className="link" onClick={() => setServing({ diversity: DEFAULT_DIVERSITY })}>reset</button>}
      </label>
    </div>
  );
}

export function Shelf({ recs, loading, onUpdate, pending, emptyHint }: {
  recs: Recs | Unavailable | null; loading: boolean; onUpdate?: () => void; pending?: number; emptyHint?: string;
}) {
  const { setInsight, insightOpen, notify, watchedIds } = useDemo();
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
          {onUpdate && <ServingControls />}
        </div>
        {onUpdate && (
          <button className="btn primary" onClick={onUpdate} disabled={loading} title="Ask GraphRec for a fresh list using everything you've watched">
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
