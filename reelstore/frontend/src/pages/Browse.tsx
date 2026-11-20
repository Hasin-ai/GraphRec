import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { FilmTile } from "../components/FilmTile";
import { useDemo } from "../demo";
import type { FilmPage, Genre, SortKey, Tag } from "../types";

const LIMIT = 30;
const SORTS: { key: SortKey; label: string }[] = [
  { key: "popular", label: "Most watched" },
  { key: "newest", label: "Newest" },
  { key: "oldest", label: "Oldest" },
  { key: "title", label: "Title A–Z" },
];

export function Browse() {
  const { genre } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { watchedIds } = useDemo();
  const q = params.get("q") ?? "";
  const tag = params.get("tag") ?? "";
  const sort = (params.get("sort") as SortKey | null) ?? "popular";
  const pageNo = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const offset = (pageNo - 1) * LIMIT;

  const [genres, setGenres] = useState<Genre[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [page, setPage] = useState<FilmPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.genres().then(setGenres).catch(() => undefined);
    api.tags(24).then(setTags).catch(() => undefined);
  }, []);
  useEffect(() => {
    let live = true;
    setLoading(true);
    const t = window.setTimeout(() => {
      api.films({ genre, tag: tag || undefined, q: q || undefined, sort, offset, limit: LIMIT })
        .then((p) => { if (live) { setPage(p); setError(null); } })
        .catch((e) => { if (live) { setPage(null); setError((e as Error).message); } })
        .finally(() => { if (live) setLoading(false); });
    }, 120);
    return () => { live = false; window.clearTimeout(t); };
  }, [genre, tag, q, sort, offset]);

  /** Change some params; any filter change goes back to page 1. */
  const update = (patch: Record<string, string | null>, keepPage = false) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!keepPage) next.delete("page");
    setParams(next);
  };
  const goPage = (n: number) => { update({ page: n > 1 ? String(n) : null }, true); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const keep = (to: string) => { const next = new URLSearchParams(params); next.delete("page"); const s = next.toString(); return s ? `${to}?${s}` : to; };

  const heading = q ? `Results for “${q}”` : tag ? `Tagged “${tag}”` : genre ?? "All films";
  const filtered = Boolean(genre || tag || q);
  const pages = page ? Math.max(1, Math.ceil(page.total / LIMIT)) : 1;

  return (
    <div className="page">
      <div className="browse-head">
        <div>
          <h1>{heading}</h1>
          <p className="muted" aria-live="polite">
            {page ? `${page.total.toLocaleString()} ${page.total === 1 ? "film" : "films"}` : loading ? "Loading…" : ""}
            {page && (genre && (q || tag)) ? ` in ${genre}` : ""}
            {filtered && <> · <button className="linkish" onClick={() => navigate("/browse")}>Clear all filters</button></>}
          </p>
        </div>
        <label className="sort">Sort
          <select value={sort} onChange={(e) => update({ sort: e.target.value === "popular" ? null : e.target.value })}>
            {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </label>
      </div>

      <div className="filter-group">
        <span className="filter-label">Genre</span>
        <div className="chips">
          <Link className={`chip ${!genre ? "on" : ""}`} to={keep("/browse")}>All</Link>
          {genres.map((g) => (
            <Link key={g.name} className={`chip ${g.name === genre ? "on" : ""}`} to={keep(`/browse/${encodeURIComponent(g.name)}`)}>
              {g.name}<span>{g.films.toLocaleString()}</span>
            </Link>
          ))}
        </div>
      </div>
      <div className="filter-group">
        <span className="filter-label">Viewer tags</span>
        <div className="chips">
          {tag && !tags.some((t) => t.name === tag) && <button className="chip tag on" onClick={() => update({ tag: null })}>{tag} ✕</button>}
          {tags.map((t) => (
            <button key={t.name} className={`chip tag ${t.name === tag ? "on" : ""}`} aria-pressed={t.name === tag}
              onClick={() => update({ tag: t.name === tag ? null : t.name })}>
              {t.name}{t.name === tag ? " ✕" : ""}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="notice bad">Couldn't load films: {error} <button className="btn small" onClick={() => update({}, true)}>Retry</button></div>}
      {page && page.total === 0 && (
        <div className="empty">
          <h3>No films match</h3>
          <p className="muted">Try a shorter search, another tag, or <button className="linkish" onClick={() => navigate("/browse")}>clear all filters</button>.</p>
        </div>
      )}
      <div className={`grid ${loading ? "is-loading" : ""}`}>
        {page?.items.map((f) => <FilmTile key={f.id} film={f} watched={watchedIds.has(f.id)} />)}
      </div>
      {page && pages > 1 && (
        <nav className="pager" aria-label="Pages">
          <button className="btn" disabled={pageNo <= 1} onClick={() => goPage(pageNo - 1)}>← Previous</button>
          <span>Page {pageNo} of {pages.toLocaleString()} · {offset + 1}–{Math.min(offset + LIMIT, page.total)} of {page.total.toLocaleString()}</span>
          <button className="btn" disabled={pageNo >= pages} onClick={() => goPage(pageNo + 1)}>Next →</button>
        </nav>
      )}
    </div>
  );
}
