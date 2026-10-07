import { api, isUnavailable } from "../api";
import { strategyDetail, strategyLabel, useDemo } from "../demo";
import type { Recs, Unavailable } from "../types";
import { FilmTile } from "./FilmTile";

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
          </div>
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
