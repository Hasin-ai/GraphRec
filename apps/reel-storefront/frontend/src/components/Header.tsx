import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { useDemo } from "../demo";
import type { Persona } from "../types";

/** "Classic Disney and family animation (MovieLens user 184387)" -> "Classic Disney and family animation". */
const taste = (p: Persona) => p.blurb.replace(/\s*\(.*\)\s*$/, "");
const label = (p: Persona) => (p.userId ? `${p.name} — ${taste(p)}` : "Guest (no history)");

export function Header() {
  const { session, switchPersona, resetGuest, insightOpen, setInsight, notify, history } = useDemo();
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const [q, setQ] = useState("");
  // Keep the box in sync with the Browse page's query (back/forward, chip clicks).
  useEffect(() => {
    setQ(location.pathname.startsWith("/browse") ? new URLSearchParams(location.search).get("q") ?? "" : "");
  }, [location.pathname, location.search]);

  const current = session?.persona;
  const choose = async (key: string) => {
    if (!current || key === current.key) return;
    const carry = current.userId === null && key !== "anon";
    setBusy(true);
    try { await switchPersona(key, carry); } catch (e) { notify((e as Error).message); } finally { setBusy(false); }
  };
  const reset = async () => {
    setBusy(true);
    try { await resetGuest(); } catch (e) { notify((e as Error).message); } finally { setBusy(false); }
  };
  const search = (e: FormEvent) => {
    e.preventDefault();
    const term = q.trim();
    navigate(term ? `/browse?q=${encodeURIComponent(term)}` : "/browse");
  };
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="Reel home"><span className="brand-mark">▶</span>Reel</Link>
      <nav className="nav">
        <NavLink to="/" end>Home</NavLink>
        <NavLink to="/browse">Browse</NavLink>
      </nav>
      <form className="topsearch" role="search" onSubmit={search}>
        <input type="search" placeholder="Search titles, actors, themes…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search films" />
      </form>
      <div className="topbar-right">
        <label className="persona" title={current ? (current.userId ? `${current.blurb}` : "A new visitor: picks come from this visit only") : ""}>
          <span className="persona-label">Viewing as</span>
          <span className="dot" style={{ background: current?.color ?? "#999" }} />
          <select value={current?.key ?? "anon"} onChange={(e) => choose(e.target.value)} disabled={busy || !session} aria-label="Viewing as shopper">
            {session?.personas.map((p) => <option key={p.key} value={p.key}>{label(p)}</option>)}
          </select>
        </label>
        {current && current.userId === null && (
          <button className="btn ghost small" onClick={reset} disabled={busy || history.length === 0}
            title={history.length ? "Forget this visit's films and start over as a brand-new guest" : "Nothing to reset yet"}>
            Reset guest
          </button>
        )}
        <button className={`btn ghost small ${insightOpen ? "on" : ""}`} onClick={() => setInsight(!insightOpen)} aria-pressed={insightOpen}
          title="Show what GraphRec did for each click">How it works</button>
      </div>
    </header>
  );
}
