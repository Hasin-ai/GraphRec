import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { displayTitle, Poster } from "../components/FilmTile";
import { Shelf } from "../components/Shelf";
import { useDemo } from "../demo";
import type { Film, Receipt, Recs, Unavailable } from "../types";

function popularityLine(f: Film): string {
  if (f.popularityRank <= 100) return `One of the 100 most-watched films here (#${f.popularityRank})`;
  if (f.popularityRank <= 1000) return `Popular · #${f.popularityRank.toLocaleString()} of 7,951`;
  return `#${f.popularityRank.toLocaleString()} of 7,951 by how often it was watched`;
}

export function FilmPage() {
  const { id = "" } = useParams();
  const from = (useLocation().state ?? undefined) as { requestId: string; position: number } | undefined;
  const { watch, notify, setLastTrace, watchedIds, insightOpen, appliedServing: serving } = useDemo();
  const [film, setFilm] = useState<Film | null>(null);
  const [missing, setMissing] = useState(false);
  const [more, setMore] = useState<Recs | Unavailable | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setFilm(null); setMore(null); setReceipt(null); setMissing(false);
    let current = true;
    api.film(id).then((f) => {
      if (!current) return;
      setFilm(f); document.title = `${displayTitle(f.title)} · Reel`;
      // Ask for similar films only for a film that exists (an unknown id would be a 422).
      return api.recommend("more_like", id, serving).then((r) => { if (current) { setMore(r); if ("trace" in r) setLastTrace(r); } });
    }).catch((e) => {
      if (!current) return;
      if (e instanceof ApiError && e.code === "not_found") setMissing(true); else notify((e as Error).message);
    });
    window.scrollTo({ top: 0 });
    return () => { current = false; document.title = "Reel — a GraphRec film store"; };
  }, [id, notify, setLastTrace, serving]);

  if (missing) {
    return (
      <div className="page empty">
        <h1>We couldn't find that film</h1>
        <p className="muted">It may not be part of this catalogue.</p>
        <p><Link className="btn primary" to="/browse">Browse all films</Link></p>
      </div>
    );
  }
  if (!film) return <div className="page"><div className="film"><div className="poster large placeholder ghost" /><div className="film-body"><div className="line-ghost" /></div></div></div>;

  const watched = watchedIds.has(film.id) || Boolean(receipt && !receipt.duplicate);
  const onWatch = async () => {
    setBusy(true);
    try { setReceipt(await watch(film.id, from)); } catch (e) { notify((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to="/">Home</Link> › <Link to={`/browse/${encodeURIComponent(film.genres[0] ?? "")}`}>{film.genres[0] ?? "Films"}</Link> › <span>{displayTitle(film.title)}</span>
      </nav>
      <section className="film">
        <Poster film={film} large />
        <div className="film-body">
          <h1>{displayTitle(film.title)} {film.year && <span className="muted">({film.year})</span>}</h1>
          <div className="chips" aria-label="Genres">
            {film.genres.map((g) => <Link key={g} className="chip" to={`/browse/${encodeURIComponent(g)}`}>{g}</Link>)}
          </div>
          {film.tags.length > 0 && (
            <div className="film-tags">
              <h4>What viewers say</h4>
              <div className="chips">
                {film.tags.map((t) => <Link key={t} className="chip tag" to={`/browse?tag=${encodeURIComponent(t)}`} title={`More films tagged “${t}”`}>#{t}</Link>)}
              </div>
            </div>
          )}
          <p className="muted">{popularityLine(film)}</p>
          <div className="actions">
            {watched
              ? <button className="btn big done" disabled aria-label="Already in your history">✓ In your history</button>
              : <button className="btn primary big" onClick={onWatch} disabled={busy}>{busy ? "Saving…" : "I've watched this"}</button>}
            {film.tmdbId && <a className="btn ghost" href={`https://www.themoviedb.org/movie/${film.tmdbId}`} target="_blank" rel="noreferrer">Details on TMDB ↗</a>}
            {film.imdbId && <a className="btn ghost" href={`https://www.imdb.com/title/tt${film.imdbId}/`} target="_blank" rel="noreferrer">IMDb ↗</a>}
          </div>
          {receipt && (
            <p className={`receipt ${receipt.duplicate ? "dup" : "ok"}`}>
              {receipt.duplicate ? "This was already in your history." : <>Saved to your history. <Link to="/">See your updated picks →</Link></>}
              {insightOpen && <small> GraphRec {receipt.duplicate ? "already had" : "recorded"} <code>{receipt.eventType}</code> event <code>{receipt.eventId}</code> in {receipt.latencyMs} ms{receipt.feedback ? ` · ${receipt.feedback} feedback` : ""}.</small>}
            </p>
          )}
          <p className="fineprint">Marking a film as watched tells the recommender what you like; it shapes the picks on your Home page.</p>
        </div>
      </section>
      <Shelf recs={more} loading={false} emptyHint="No similar films found." />
    </div>
  );
}
