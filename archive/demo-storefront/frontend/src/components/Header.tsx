import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { useStore } from "../lib/store";
import type { Persona } from "../lib/types";

export function Avatar({ persona, size = 30 }: { persona: Persona; size?: number }) {
  const guest = persona.userId === null;
  return <span aria-hidden="true" className={`fct-avatar ${guest ? "guest" : ""}`} style={{ width: size, height: size, background: persona.color }} />;
}

function PersonaSwitcher() {
  const { session, persona, switchPersona, switching } = useStore();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!session || !persona) {
    return (
      <button type="button" className="btn btn-secondary fct-persona-btn" disabled aria-busy="true">
        <span className="fct-avatar" style={{ background: "var(--color-neutral-300)" }} />
        <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", lineHeight: 1.15 }}>
          <span className="fct-kicker">Demo shopper</span>
          <span style={{ fontSize: 14, fontWeight: 600 }}>…</span>
        </span>
      </button>
    );
  }

  const pick = (key: string) => {
    setOpen(false);
    if (key !== persona.key) void switchPersona(key);
  };

  return (
    <div style={{ position: "relative" }} ref={wrap}>
      <button type="button" className="btn btn-secondary fct-persona-btn" onClick={() => setOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={open} aria-busy={switching || undefined}>
        <Avatar persona={persona} />
        <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", lineHeight: 1.15 }}>
          <span className="fct-kicker">Demo shopper</span>
          <span style={{ fontSize: 14, fontWeight: 600 }}>{persona.name}</span>
        </span>
        <span aria-hidden="true" style={{ fontSize: 10, color: "var(--ink-2)" }}>
          ▾
        </span>
      </button>
      {open && (
        <ul role="listbox" aria-label="Demo shopper" className="fct-persona-menu elev-lg fct-rise">
          <li className="fct-kicker" style={{ padding: "var(--space-2) var(--space-3) var(--space-1)" }}>
            Switch persona · not a login
          </li>
          {session.personas.map((p) => (
            <li key={p.key} role="none">
              <button
                type="button"
                role="option"
                aria-selected={p.key === persona.key}
                className="fct-persona-option"
                onClick={() => pick(p.key)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    pick(p.key);
                  }
                }}
              >
                <Avatar persona={p} />
                <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                  <span style={{ fontSize: 14, fontWeight: 600 }}>{p.name}</span>
                  <span style={{ fontSize: 12, color: "var(--ink-2)" }}>{p.blurb}</span>
                </span>
                <span aria-hidden="true" className="check" style={{ opacity: p.key === persona.key ? 1 : 0 }}>
                  ✓
                </span>
              </button>
            </li>
          ))}
          <li style={{ padding: "var(--space-2) var(--space-3)", fontSize: 11, color: "var(--ink-2)", borderTop: "1px solid var(--color-divider)", marginTop: "var(--space-1)" }}>
            Switching changes the demo cookie, the recommendation call and the local cart namespace.
          </li>
        </ul>
      )}
    </div>
  );
}

export function Header() {
  const { count, setDrawerOpen } = useStore();
  return (
    <header className="nav fct-header">
      <NavLink to="/" className="fct-brand">
        FACET
      </NavLink>
      <nav className="fct-nav" aria-label="Primary">
        <NavLink to="/" end>
          Shop
        </NavLink>
        <NavLink to="/demo/compare">Compare</NavLink>
      </nav>
      <PersonaSwitcher />
      <button type="button" className="btn btn-secondary" style={{ gap: 8 }} onClick={() => setDrawerOpen(true)} aria-label={`Cart, ${count} items`}>
        <span>Cart</span>
        <span aria-hidden="true" className={`fct-cart-badge ${count ? "has" : ""}`}>
          {count}
        </span>
      </button>
    </header>
  );
}
