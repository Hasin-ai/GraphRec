import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { proofExplainer } from "../lib/proof";
import { useStore } from "../lib/store";

/**
 * Read-only demo controls: session identity, the last recommendation's provenance,
 * API health and the proof-status legend. Unlike the design prototype there is no
 * "force a state" switch here - every value comes from the server.
 */
export function DemoRail() {
  const { railOpen, setRailOpen, session, persona, lastProvenance, health, refreshHealth, isGuest } = useStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (railOpen) void refreshHealth();
  }, [railOpen, refreshHealth]);

  useEffect(() => {
    if (!railOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setRailOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [railOpen, setRailOpen]);

  if (!railOpen) {
    return (
      <button type="button" className="btn elev-md fct-rail-tab" onClick={() => setRailOpen(true)} aria-expanded={false}>
        Demo rail
      </button>
    );
  }

  const rows: [string, string][] = [
    ["persona cookie", `facet_demo_user=${persona?.key ?? "…"}`],
    ["graphrec user", persona?.userId ?? "none (session-based)"],
    ["session", session?.sessionId ?? "…"],
    ["request", lastProvenance?.requestId ?? "—"],
    ["model", lastProvenance?.modelVersionId ?? (lastProvenance ? "n/a (fallback)" : "—")],
    ["raw strategy", lastProvenance?.rawStrategy ?? "—"],
    ["health", health ? `${health.graphrec}${health.catalogProducts !== null ? ` · ${health.catalogProducts} products` : ""}` : "checking…"],
    ["proof config", health ? (health.proofConfigured ? `verified for ${health.proofVersionId}` : "MODEL_PROOF_VERIFIED=false") : "…"],
  ];

  return (
    <aside aria-label="Demo controls" className="fct-rail elev-lg fct-slide">
      <header>
        <span style={{ display: "flex", flexDirection: "column" }}>
          <span className="fct-kicker">Demo controls</span>
          <span className="title">Session &amp; provenance</span>
        </span>
        <button type="button" className="btn btn-icon btn-secondary" onClick={() => setRailOpen(false)} aria-label="Close demo controls">
          ✕
        </button>
      </header>

      <section>
        <h3>Session</h3>
        <dl>
          {rows.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        <p className="note">Identity comes from this window's cookies. Open another browser window to act as a second shopper at the same time.</p>
      </section>

      <section>
        <h3>Proof status</h3>
        <ul className="fct-legend">
          <li>
            <span className="fct-dot" style={{ background: "var(--verified)" }} />
            <span>
              <strong>Model-backed</strong> — only after <code>verify_personalization.py</code> passed for the exact active model version and the operator set <code>MODEL_PROOF_VERIFIED</code>.
            </span>
          </li>
          <li>
            <span className="fct-dot" style={{ background: "var(--preview)" }} />
            <span>
              <strong>Serving preview</strong> — the live serving path answered with a model version, but the query is not yet user-specific.
            </span>
          </li>
          <li>
            <span className="fct-dot" style={{ background: "var(--ink-2)" }} />
            <span>
              <strong>Catalog fallback</strong> — GraphRec answered from the catalog, not a model.
            </span>
          </li>
        </ul>
        {lastProvenance && <p className="note">Current: {proofExplainer(lastProvenance.proofStatus)}</p>}
        {isGuest && !lastProvenance && <p className="note">New visitor: expect a catalog fallback.</p>}
      </section>

      <section>
        <h3>How this demo works</h3>
        <p className="note" style={{ marginTop: 0 }}>
          The browser talks only to the storefront server. The server holds the GraphRec API key, translates your clicks into events, requests Top-N recommendations and sends impression and click feedback. Products,
          prices and orders are fictional; nothing is charged.
        </p>
        <button
          type="button"
          className="btn btn-secondary btn-block"
          onClick={() => {
            setRailOpen(false);
            navigate("/demo/compare");
          }}
        >
          Open the compare lab
        </button>
      </section>
    </aside>
  );
}
