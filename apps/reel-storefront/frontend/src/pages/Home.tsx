import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { FilmTile } from "../components/FilmTile";
import { Shelf } from "../components/Shelf";
import { useDemo } from "../demo";
import type { Film, Genre, Tag } from "../types";

export function Home() {
  const { session, home, homeLoading, refreshHome, pendingSinceRefresh, history, watchedIds, autoRefresh } = useDemo();
  const [genres, setGenres] = useState<Genre[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [popular, setPopular] = useState<Film[]>([]);
  useEffect(() => {
    api.genres().then(setGenres).catch(() => undefined);
    api.tags(18).then(setTags).catch(() => undefined);
    api.films({ limit: 12 }).then((p) => setPopular(p.items)).catch(() => undefined);
  }, []);
  const p = session?.persona;
  const recent = history.slice(0, 12);
  return (
    <div className="page">
      <section className="hero">
        <h1>{p?.userId ? `Welcome back, ${p.name}` : "Find your next film"}</h1>
        <p>
          {p?.userId
            ? `Your picks are built from the ${(history.length || p.historyLength).toLocaleString()} films in your history. Mark more films as watched and they'll adapt.`
            : "Open any film and press “I've watched this” — your picks will start following your taste."}
        </p>
      </section>
      <Shelf recs={home} loading={homeLoading} onUpdate={refreshHome} pending={autoRefresh ? 0 : pendingSinceRefresh} />

      {recent.length > 0 && (
        <section className="block">
          <div className="block-head">
            <h3>Recently watched</h3>
            <span className="muted">{history.length.toLocaleString()} in your history</span>
          </div>
          <div className="row">{recent.map((f, i) => <FilmTile key={`${f.id}-${i}`} film={f} watched />)}</div>
        </section>
      )}

      <section className="block">
        <h3>Explore by theme</h3>
        <div className="chips">
          {tags.map((t) => <Link key={t.name} className="chip tag" to={`/browse?tag=${encodeURIComponent(t.name)}`}>#{t.name}<span>{t.films}</span></Link>)}
        </div>
      </section>
      <section className="block">
        <h3>Browse by genre</h3>
        <div className="chips">
          {genres.map((g) => <Link key={g.name} className="chip" to={`/browse/${encodeURIComponent(g.name)}`}>{g.name}<span>{g.films.toLocaleString()}</span></Link>)}
        </div>
      </section>
      <section className="block">
        <div className="block-head">
          <h3>Most watched</h3>
          <Link className="muted" to="/browse">See all →</Link>
        </div>
        <div className="grid">{popular.map((f) => <FilmTile key={f.id} film={f} watched={watchedIds.has(f.id)} />)}</div>
      </section>
    </div>
  );
}
