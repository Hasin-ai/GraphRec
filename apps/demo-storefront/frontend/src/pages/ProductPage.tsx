import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Shelf } from "../components/Shelf";
import { Skeleton, Tile } from "../components/Tile";
import { api, ApiError } from "../lib/api";
import { cartProductIds } from "../lib/cart";
import { categoryLabel, money } from "../lib/format";
import { useStore } from "../lib/store";
import type { Product } from "../lib/types";
import { useRecommendations } from "../lib/useRecommendations";

type State = { phase: "loading" } | { phase: "ok"; product: Product } | { phase: "error"; error: ApiError };

export function ProductPage() {
  const { id = "" } = useParams();
  const { cart, addToCart, announce, showToast, noteViewed, session } = useStore();
  const [state, setState] = useState<State>({ phase: "loading" });
  const [qty, setQtyLocal] = useState(1);
  const personaKey = session?.persona.key;

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    setQtyLocal(1);
    window.scrollTo(0, 0);
    api
      .product(id)
      .then((product) => {
        if (cancelled) return;
        setState({ phase: "ok", product });
        announce("Product loaded. View tracked.");
      })
      .catch((error: ApiError) => !cancelled && setState({ phase: "error", error }));
    return () => {
      cancelled = true;
    };
  }, [id, announce]);

  // Track the view once the product has loaded, for the current shopper.
  useEffect(() => {
    if (state.phase !== "ok" || !personaKey) return;
    noteViewed(state.product.externalId);
    void api.event({ action: "view", productId: state.product.externalId, surface: "product_detail" }).then((ok) => {
      if (!ok) showToast({ message: "Could not record that view event. Browsing is unaffected.", kind: "warn" });
    });
  }, [state, personaKey, noteViewed, showToast]);

  const exclude = useMemo(() => Array.from(new Set([...cartProductIds(cart), id])), [cart, id]);
  const shelf = useRecommendations({ topN: 5, exclude, surface: "product_detail", enabled: state.phase === "ok" });

  return (
    <main className="fct-main" style={{ paddingTop: "var(--space-6)" }}>
      <Link to="/" className="btn btn-ghost" style={{ marginBottom: "var(--space-4)", fontSize: 13 }}>
        ← All products
      </Link>

      {state.phase === "loading" && (
        <div className="fct-detail" aria-busy="true">
          <Skeleton style={{ aspectRatio: "4 / 5", borderRadius: "var(--radius-lg)" }} />
          <div>
            <Skeleton style={{ height: 16, width: "30%", borderRadius: 999 }} />
            <Skeleton style={{ height: 40, width: "80%", borderRadius: 999, marginTop: 16 }} />
            <Skeleton style={{ height: 14, width: "100%", borderRadius: 999, marginTop: 24 }} />
            <Skeleton style={{ height: 14, width: "92%", borderRadius: 999, marginTop: 10 }} />
          </div>
        </div>
      )}

      {state.phase === "error" && (
        <div className="fct-error" role="alert">
          <p className="title">{state.error.status === 404 ? "This product is not in the store" : "The product could not be loaded"}</p>
          <p className="body">
            {state.error.message}
            {state.error.correlationId && (
              <>
                {" "}
                Correlation ID <code>{state.error.correlationId}</code>
              </>
            )}
          </p>
          <Link to="/" className="btn btn-secondary">
            Browse all products
          </Link>
        </div>
      )}

      {state.phase === "ok" && (
        <>
          <section className="fct-detail">
            <Tile id={state.product.externalId} category={state.product.category} accent={state.product.accent} dim={!state.product.available} />
            <div style={{ minWidth: 0, paddingTop: "var(--space-2)" }}>
              <p className="fct-eyebrow">
                {categoryLabel(state.product.category)}
                {state.product.brand ? ` · ${state.product.brand}` : ""}
              </p>
              <h1>{state.product.title}</h1>
              <p className="fct-price">{money(state.product.price)}</p>
              <p className="fct-desc">{state.product.description}</p>
              {state.product.tags.length > 0 && (
                <p style={{ margin: "0 0 var(--space-4)", display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {state.product.tags.map((t) => (
                    <span key={t} className="tag tag-neutral">
                      {t}
                    </span>
                  ))}
                </p>
              )}
              <p className="fct-avail" style={{ color: state.product.available ? "var(--verified)" : "var(--error)" }}>
                <span aria-hidden="true" className="fct-dot" style={{ background: state.product.available ? "var(--verified)" : "var(--error)" }} />
                <span>{state.product.available ? "Available · fictional stock" : "Unavailable — not orderable in this demo"}</span>
              </p>
              <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center", flexWrap: "wrap" }}>
                <div className="fct-stepper" role="group" aria-label="Quantity">
                  <button type="button" className="btn btn-icon" onClick={() => setQtyLocal((q) => Math.max(1, q - 1))} aria-label="Decrease quantity" disabled={!state.product.available}>
                    −
                  </button>
                  <span className="qty" aria-live="polite">
                    {qty}
                  </span>
                  <button type="button" className="btn btn-icon" onClick={() => setQtyLocal((q) => Math.min(9, q + 1))} aria-label="Increase quantity" disabled={!state.product.available}>
                    +
                  </button>
                </div>
                <button type="button" className="btn btn-primary" style={{ padding: "12px 26px", fontSize: 15 }} disabled={!state.product.available} onClick={() => addToCart(state.product, qty)}>
                  {state.product.available ? "Add to cart" : "Unavailable"}
                </button>
              </div>
              <dl className="fct-facts">
                {state.product.size && (
                  <div>
                    <dt>Size</dt>
                    <dd>{state.product.size}</dd>
                  </div>
                )}
                <div>
                  <dt>Category</dt>
                  <dd>{categoryLabel(state.product.category)}</dd>
                </div>
                <div>
                  <dt>SKU</dt>
                  <dd className="mono">{state.product.externalId}</dd>
                </div>
              </dl>
            </div>
          </section>

          <div style={{ marginTop: "var(--space-8)" }}>
            <Shelf shelf={shelf} surface="product_detail" variant="related" headingSize={28} />
          </div>
        </>
      )}
    </main>
  );
}
