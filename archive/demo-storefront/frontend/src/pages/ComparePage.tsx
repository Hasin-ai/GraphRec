import { useCallback, useEffect, useState } from "react";
import { Avatar } from "../components/Header";
import { Skeleton } from "../components/Tile";
import { api, ApiError } from "../lib/api";
import { cartProductIds } from "../lib/cart";
import { categoryLabel, money, shortId, swatchStyle } from "../lib/format";
import { proofIcon, proofPillLabel, proofTone } from "../lib/proof";
import { useStore } from "../lib/store";
import type { Compare } from "../lib/types";

type State = { phase: "loading" } | { phase: "ok"; data: Compare; run: number; identicalToPrevious: boolean | null } | { phase: "error"; error: ApiError };

const TOP_N_OPTIONS = [3, 5, 8, 10];

/** The proof surface: one identical Top-N request for every shopper, side by side. */
export function ComparePage() {
  const { cart } = useStore();
  const [topN, setTopN] = useState(5);
  const [excludeCart, setExcludeCart] = useState(false);
  const [state, setState] = useState<State>({ phase: "loading" });
  const [previous, setPrevious] = useState<string | null>(null);

  const run = useCallback(
    async (runNumber: number) => {
      setState((s) => (s.phase === "ok" ? s : { phase: "loading" }));
      try {
        const data = await api.compare(topN, excludeCart ? cartProductIds(cart) : []);
        const signature = data.columns.map((c) => c.items.map((i) => i.externalId).join(",")).join("|");
        setState({ phase: "ok", data, run: runNumber, identicalToPrevious: previous === null ? null : previous === signature });
        setPrevious(signature);
      } catch (error) {
        setState({ phase: "error", error: error as ApiError });
      }
    },
    [topN, excludeCart, cart, previous],
  );

  useEffect(() => {
    setPrevious(null);
    void run(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topN, excludeCart]);

  const data = state.phase === "ok" ? state.data : null;
  const gateTone = data?.summary.gatePassed ? "verified" : "preview";

  return (
    <main className="fct-main" style={{ paddingTop: "var(--space-6)", paddingBottom: "var(--space-8)" }}>
      <div className="fct-compare-head">
        <div style={{ minWidth: 0 }}>
          <p className="fct-eyebrow">Demo controls · compare users</p>
          <h1>Same request, four shoppers.</h1>
          <p style={{ margin: 0, fontSize: 14, color: "var(--ink-2)", maxWidth: "62ch", textWrap: "pretty" }}>
            Top-{topN} · {excludeCart ? `shared exclusions: ${cartProductIds(cart).length} cart product(s)` : "no exclusions"} · identical request body for every shopper · each request is sent twice to check the
            ordering repeats.
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>
          <label className="fct-kicker" style={{ display: "flex", alignItems: "center", gap: 6 }}>
            Top-N
            <select className="input" style={{ width: "auto", minHeight: 34 }} value={topN} onChange={(e) => setTopN(Number(e.target.value))} aria-label="Top-N">
              {TOP_N_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="radio" style={{ fontSize: 12 }}>
            <input type="checkbox" checked={excludeCart} onChange={(e) => setExcludeCart(e.target.checked)} style={{ position: "static", opacity: 1, width: "auto", height: "auto" }} />
            <span>Exclude my cart</span>
          </label>
          {state.phase === "ok" && <span style={{ fontSize: 12, color: "var(--ink-2)" }}>Run {state.run}</span>}
          <button type="button" className="btn btn-primary" style={{ padding: "10px 20px" }} onClick={() => void run(state.phase === "ok" ? state.run + 1 : 1)} disabled={state.phase === "loading"}>
            Re-run Top-N
          </button>
        </div>
      </div>

      {state.phase === "ok" && state.identicalToPrevious !== null && (
        <p className={`fct-banner fct-rise ${state.identicalToPrevious ? "verified" : "preview"}`}>
          {state.identicalToPrevious ? "Re-run produced identical rankings for every shopper. Ordering is repeatable." : "Re-run produced different rankings from the previous run — ordering is not stable."}
        </p>
      )}

      {state.phase === "error" && (
        <div className="fct-error" role="alert">
          <p className="title">The compare lab could not reach the storefront</p>
          <p className="body">{state.error.message}</p>
          <button type="button" className="btn btn-primary" onClick={() => void run(1)}>
            Retry
          </button>
        </div>
      )}

      {state.phase === "loading" && (
        <div className="fct-columns" aria-busy="true">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} style={{ height: 360, borderRadius: "calc(var(--radius-lg) * 1.15)" }} />
          ))}
        </div>
      )}

      {data && (
        <>
          <div className="fct-columns">
            {data.columns.map((col) => {
              const tone = col.provenance ? proofTone(col.provenance.proofStatus) : "error";
              return (
                <section key={col.persona.key} className="card elev-sm fct-column" aria-label={`${col.persona.name} results`}>
                  <header>
                    <Avatar persona={col.persona} size={34} />
                    <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                      <span className="name">{col.persona.name}</span>
                      <span style={{ fontSize: 12, color: "var(--ink-2)" }}>{col.persona.userId ?? "session-based · no history"}</span>
                    </span>
                  </header>

                  {col.error ? (
                    <p className="fct-pill error" role="alert">
                      <span aria-hidden="true">!</span>
                      <span>{col.error}</span>
                    </p>
                  ) : (
                    <ol>
                      {col.items.map((it) => (
                        <li key={it.externalId} className={it.shared ? "shared" : ""} title={it.shared ? "Appears in every shopper's list" : undefined}>
                          <span aria-hidden="true" className="fct-swatch" style={swatchStyle(it.category, 26, it.accent)} />
                          <span style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
                            <span className="t">
                              {it.position}. {it.title}
                            </span>
                            <span className="s">
                              {categoryLabel(it.category)} · {money(it.price)}
                              {it.shared ? " · in all lists" : ""}
                            </span>
                          </span>
                        </li>
                      ))}
                      {col.items.length === 0 && <li style={{ justifyContent: "center", fontSize: 12, color: "var(--ink-2)" }}>empty result</li>}
                    </ol>
                  )}

                  <dl>
                    <div>
                      <dt>raw strategy</dt>
                      <dd>{col.provenance?.rawStrategy ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>model</dt>
                      <dd title={col.provenance?.modelVersionId ?? undefined}>{shortId(col.provenance?.modelVersionId)}</dd>
                    </div>
                    <div>
                      <dt>repeatable</dt>
                      <dd>{col.repeatable === null ? "—" : col.repeatable ? "yes" : "no"}</dd>
                    </div>
                    <div>
                      <dt>excluded</dt>
                      <dd>{col.provenance?.excludedCount ?? 0}</dd>
                    </div>
                  </dl>

                  {col.provenance && (
                    <p className={`fct-pill ${tone}`}>
                      <span aria-hidden="true">{proofIcon(col.provenance.proofStatus)}</span>
                      <span>{proofPillLabel(col.provenance.proofStatus)}</span>
                    </p>
                  )}
                </section>
              );
            })}
          </div>

          <section style={{ marginTop: "var(--space-8)" }}>
            <h2 style={{ fontSize: 26, margin: "0 0 var(--space-3)" }}>Similarity summary</h2>
            <div className="fct-summary">
              <div className="card">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Pair</th>
                      <th style={{ textAlign: "right" }}>Overlap</th>
                      <th style={{ textAlign: "right" }}>Jaccard</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.pairs.map((p) => (
                      <tr key={`${p.a}-${p.b}`}>
                        <td style={{ fontSize: 13 }}>
                          {p.a} ↔ {p.b}
                        </td>
                        <td className="mono" style={{ textAlign: "right", fontSize: 13 }}>
                          {p.overlap} / {data.summary.topN}
                        </td>
                        <td className="mono" style={{ textAlign: "right", fontSize: 13 }}>
                          {p.jaccard.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                    {data.pairs.length === 0 && (
                      <tr>
                        <td colSpan={3} style={{ fontSize: 13, color: "var(--ink-2)" }}>
                          No comparable results.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="card">
                <dl style={{ margin: 0, display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                  {[
                    ["Unique products across shoppers", `${data.summary.uniqueProducts} of ${data.summary.slots} slots`],
                    ["Distinct ranking orders", `${data.summary.distinctOrderings} of ${data.columns.length}`],
                    ["Shoppers with history identical", data.summary.knownPersonasIdentical ? "Yes" : "No"],
                    ["Ordering repeatable", data.summary.allRepeatable === null ? "—" : data.summary.allRepeatable ? "Yes" : "No"],
                    ["Model version returned", data.summary.anyModelVersion ? "Yes" : "No"],
                  ].map(([label, value]) => (
                    <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: "var(--space-3)" }}>
                      <dt style={{ fontSize: 13, color: "var(--ink-2)" }}>{label}</dt>
                      <dd style={{ margin: 0, fontSize: 14, fontWeight: 600, textAlign: "right" }}>{value}</dd>
                    </div>
                  ))}
                </dl>
                <div className={`fct-gate ${gateTone}`} role="status">
                  <p className="title">
                    <span aria-hidden="true">{data.summary.gatePassed ? "✓" : "!"}</span>
                    <span>{data.summary.gatePassed ? "Proof gate passed" : "Not verified"}</span>
                  </p>
                  <p className="body">{data.summary.gateReason}</p>
                </div>
              </div>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
