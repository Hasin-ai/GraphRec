import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { proofColor, provenanceLine, shelfHeading, whyRows } from "../lib/proof";
import { useStore } from "../lib/store";
import type { Surface } from "../lib/types";
import type { ShelfState } from "../lib/useRecommendations";
import { ProductCard } from "./ProductCard";
import { CardSkeleton } from "./Tile";

interface Props {
  shelf: ShelfState;
  surface: Surface;
  variant: "home" | "related" | "continue";
  headingSize?: number;
  showRank?: boolean;
  noAdd?: boolean;
}

/**
 * A recommendation shelf with every state from the spec: loading (page stays usable),
 * content, empty, unavailable (retry + correlation id), plus the provenance line and
 * the "Why am I seeing this?" disclosure.
 */
export function Shelf({ shelf, surface, variant, headingSize = 30, showRank, noAdd }: Props) {
  const { persona, isGuest, showToast } = useStore();
  const [whyOpen, setWhyOpen] = useState(false);
  const navigate = useNavigate();
  const prov = shelf.data?.provenance ?? null;
  const heading = shelfHeading(prov?.proofStatus ?? null, persona?.name ?? "", variant);

  return (
    <section className="fct-section">
      <div className="fct-section-head">
        <h2 style={{ fontSize: headingSize }}>{heading}</h2>
        {prov && (
          <button type="button" className="btn btn-ghost" style={{ fontSize: 13 }} aria-expanded={whyOpen} onClick={() => setWhyOpen((v) => !v)}>
            Why am I seeing this?
          </button>
        )}
      </div>

      {shelf.phase === "loading" && (
        <div className="fct-shelf-grid" aria-busy="true" aria-label="Loading recommendations">
          {[1, 2, 3, 4, 5].map((i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      )}

      {shelf.phase === "empty" && (
        <div className="fct-empty">
          <p>{variant === "related" ? "Nothing related came back for this product." : "No recommendations came back for this shopper. The request succeeded with an empty result set."}</p>
          <button type="button" className="btn btn-secondary" onClick={() => navigate("/")}>
            Browse all products
          </button>
        </div>
      )}

      {shelf.phase === "error" && (
        <div className="fct-error" role="alert">
          <p className="title">Recommendation service unavailable</p>
          <p className="body">
            The catalog is unaffected. {shelf.error?.reason}
            {shelf.error?.correlationId && (
              <>
                {" "}
                Correlation ID <code>{shelf.error.correlationId}</code>
              </>
            )}
          </p>
          <div className="fct-actions">
            <button type="button" className="btn btn-primary" onClick={shelf.retry}>
              Retry
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => navigate("/")}>
              Browse all products
            </button>
          </div>
        </div>
      )}

      {shelf.phase === "ok" && shelf.data && (
        <div className="fct-shelf-grid">
          {shelf.data.items.map((item) => (
            <ProductCard
              key={item.externalId}
              product={item}
              rank={showRank ? item.position : undefined}
              noAdd={noAdd}
              compact
              onOpen={() => {
                // Feedback is sent, but navigation never waits for it.
                void api.click({ requestId: shelf.data!.provenance.requestId, productId: item.externalId, position: item.position, surface }).then((ok) => {
                  if (!ok) showToast({ message: "Could not record that click. Browsing is unaffected.", kind: "warn" });
                });
              }}
            />
          ))}
        </div>
      )}

      {(prov || shelf.phase === "loading") && (
        <p className="fct-provenance">
          <span aria-hidden="true" className="fct-dot" style={{ background: prov ? proofColor(prov.proofStatus) : "var(--color-neutral-400)" }} />
          <span>{provenanceLine(prov, persona?.name ?? "", isGuest)}</span>
        </p>
      )}

      {whyOpen && prov && (
        <dl className="fct-why fct-rise">
          {whyRows(prov).map((row) => (
            <div key={row.label} style={{ minWidth: 0 }}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
