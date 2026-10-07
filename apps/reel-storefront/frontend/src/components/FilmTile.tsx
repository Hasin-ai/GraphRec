import { Link } from "react-router-dom";
import type { Film, Ranked } from "../types";

const HUES: Record<string, number> = {
  Animation: 28, Children: 45, Comedy: 52, Romance: 345, Drama: 215, Action: 8, Adventure: 160, "Sci-Fi": 195,
  Thriller: 260, Crime: 280, Horror: 0, Fantasy: 300, Musical: 320, War: 90, Mystery: 240, Documentary: 120,
  Western: 35, "Film-Noir": 230, IMAX: 180,
};

/** MovieLens stores "Shining, The"; shoppers expect "The Shining". */
export function displayTitle(title: string): string {
  const m = /^(.*), (The|A|An|Les|La|Le|L'|Il|Das|Der|Die|El)$/.exec(title);
  return m ? `${m[2]}${m[2].endsWith("'") ? "" : " "}${m[1]}` : title;
}

export function Poster({ film, large = false }: { film: Film; large?: boolean }) {
  if (film.posterUrl) return <img className={`poster ${large ? "large" : ""}`} src={film.posterUrl} alt="" loading="lazy" />;
  const hue = HUES[film.genres[0] ?? ""] ?? 210;
  return (
    <div className={`poster placeholder ${large ? "large" : ""}`} style={{ ["--hue" as string]: hue }} aria-hidden>
      <span className="poster-title">{displayTitle(film.title)}</span>
      <span className="poster-year">{film.year ?? ""}</span>
    </div>
  );
}

function ChangeBadge({ item }: { item: Ranked }) {
  if (item.change === "new") return <span className="badge new">new</span>;
  if (item.change === "up") return <span className="badge up" title="Moved up since the last update">↑ {item.previousPosition! - item.position}</span>;
  if (item.change === "down") return <span className="badge down" title="Moved down since the last update">↓ {item.position - item.previousPosition!}</span>;
  return null;
}

export function FilmTile({ film, ranked, requestId, onOpen, watched }: {
  film: Film; ranked?: Ranked; requestId?: string; onOpen?: () => void; watched?: boolean;
}) {
  const title = displayTitle(film.title);
  const tags = (film.tags ?? []).slice(0, 3);
  return (
    <Link to={`/film/${film.id}`} className="tile" onClick={onOpen} title={`${title}${film.year ? ` (${film.year})` : ""}`}
      state={ranked && requestId ? { requestId, position: ranked.position } : undefined}>
      <div className="tile-art">
        <Poster film={film} />
        {ranked && <span className="rank">{ranked.position}</span>}
        {ranked && <ChangeBadge item={ranked} />}
        {watched && <span className="watched-mark" title="In your history">✓</span>}
      </div>
      <div className="tile-meta">
        <span className="tile-title">{title}</span>
        <span className="tile-sub">{[film.year, film.genres.slice(0, 2).join(" · ")].filter(Boolean).join(" · ")}</span>
        {tags.length > 0 && (
          <span className="tile-tags" aria-label="Viewer tags">
            {tags.map((t) => <span key={t} className="tag-mini">{t}</span>)}
          </span>
        )}
      </div>
    </Link>
  );
}
