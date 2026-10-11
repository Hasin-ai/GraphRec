import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ProductCard } from "../components/ProductCard";
import { Shelf } from "../components/Shelf";
import { CardSkeleton } from "../components/Tile";
import { api, ApiError } from "../lib/api";
import { cartProductIds } from "../lib/cart";
import { CATEGORIES, categoryLabel } from "../lib/format";
import { useStore } from "../lib/store";
import type { Product } from "../lib/types";
import { useRecommendations } from "../lib/useRecommendations";

type CatalogState = { phase: "loading" } | { phase: "ok"; items: Product[] } | { phase: "error"; error: ApiError };

export function CatalogPage() {
  const { cart, setRailOpen } = useStore();
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "";
  const [catalog, setCatalog] = useState<CatalogState>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setCatalog({ phase: "loading" });
    api
      .products()
      .then((items) => !cancelled && setCatalog({ phase: "ok", items }))
      .catch((error: ApiError) => !cancelled && setCatalog({ phase: "error", error }));
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const exclude = useMemo(() => cartProductIds(cart), [cart]);
  const shelf = useRecommendations({ topN: 5, exclude, surface: "catalog" });
  const visible = catalog.phase === "ok" ? catalog.items.filter((p) => !category || p.category === category) : [];

  return (
    <main className="fct-main">
      <section className="fct-hero">
        <div style={{ minWidth: 0 }}>
          <span className="tag tag-accent-2" style={{ marginBottom: "var(--space-3)" }}>
            A GraphRec demonstration store
          </span>
          <h1>Thoughtful everyday care.</h1>
          <p>A small store powered by GraphRec. Every shelf below is a live Top-N request, and every ranking says where it came from.</p>
          <div className="fct-actions" style={{ marginTop: "var(--space-4)" }}>
            <button type="button" className="btn btn-primary" style={{ padding: "11px 22px" }} onClick={() => setParams({ category: "skincare" })}>
              Shop skincare
            </button>
            <button type="button" className="btn btn-secondary" style={{ padding: "11px 22px" }} onClick={() => setRailOpen(true)}>
              How this demo works
            </button>
          </div>
        </div>
        <div className="fct-hero-art" aria-hidden="true">
          <span style={{ width: "52%", left: "12%", top: "16%", background: "color-mix(in srgb, #174A3A 12%, transparent)" }} />
          <span style={{ width: "34%", right: "14%", bottom: "14%", background: "color-mix(in srgb, #E58B72 34%, transparent)" }} />
          <span style={{ width: "20%", right: "34%", top: "22%", background: "color-mix(in srgb, #FFFCF7 70%, transparent)" }} />
        </div>
      </section>

      <Shelf shelf={shelf} surface="catalog" variant="home" showRank />

      <section className="fct-section" style={{ paddingBottom: "var(--space-8)" }}>
        <div className="fct-section-head" style={{ alignItems: "center" }}>
          <h2>All products</h2>
          <div className="seg" role="group" aria-label="Filter by category">
            {["", ...CATEGORIES].map((c) => (
              <label key={c || "all"} className="seg-opt">
                <input type="radio" name="fct-cat" checked={category === c} onChange={() => (c ? setParams({ category: c }) : setParams({}))} />
                <span>{c ? categoryLabel(c) : "All"}</span>
              </label>
            ))}
          </div>
        </div>

        {catalog.phase === "loading" && (
          <div className="fct-grid" aria-busy="true" aria-label="Loading catalog">
            {Array.from({ length: 8 }, (_, i) => (
              <CardSkeleton key={i} />
            ))}
          </div>
        )}

        {catalog.phase === "error" && (
          <div className="fct-error" role="alert" style={{ marginTop: "var(--space-6)" }}>
            <p className="title">The catalog could not be loaded</p>
            <p className="body">
              {catalog.error.message}
              {catalog.error.correlationId && (
                <>
                  {" "}
                  Correlation ID <code>{catalog.error.correlationId}</code>
                </>
              )}
            </p>
            <button type="button" className="btn btn-primary" onClick={() => setAttempt((n) => n + 1)}>
              Retry
            </button>
          </div>
        )}

        {catalog.phase === "ok" && (
          <>
            {visible.length === 0 ? (
              <div className="fct-empty" style={{ marginTop: "var(--space-6)" }}>
                <p>No products in this category yet.</p>
                <button type="button" className="btn btn-secondary" onClick={() => setParams({})}>
                  Show all products
                </button>
              </div>
            ) : (
              <div className="fct-grid">
                {visible.map((p) => (
                  <ProductCard key={p.externalId} product={p} withMeta />
                ))}
              </div>
            )}
          </>
        )}
      </section>
    </main>
  );
}
