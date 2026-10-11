import { Link, useLocation, useParams } from "react-router-dom";
import { Shelf } from "../components/Shelf";
import { money } from "../lib/format";
import { useStore } from "../lib/store";
import type { Purchase } from "../lib/types";
import { useRecommendations } from "../lib/useRecommendations";

/**
 * Simulated confirmation. There is no orders API: the page renders the purchase
 * receipt passed from the cart drawer. A refresh loses it, which is fine for a demo.
 */
export function OrderPage() {
  const { id = "" } = useParams();
  const { state } = useLocation() as { state?: { order?: Purchase; personaName?: string } };
  const { persona } = useStore();
  const order = state?.order;
  const shelf = useRecommendations({ topN: 5, exclude: order?.lines.map((l) => l.productId) ?? [], surface: "order" });

  return (
    <main className="fct-main" style={{ paddingTop: "var(--space-8)" }}>
      <section className="fct-order">
        <div style={{ minWidth: 0 }}>
          <span className="tag tag-accent-2">Simulated · no payment taken</span>
          <h1>Thank you{persona ? `, ${state?.personaName ?? persona.name}` : ""}.</h1>
          <p style={{ margin: "0 0 var(--space-4)", fontSize: 16, color: "var(--ink-2)", maxWidth: "46ch" }}>
            Order <strong className="mono">{id}</strong> was recorded against the demo session. Nothing was charged and no inventory moved.
          </p>
          <div className="fct-actions">
            <Link to="/" className="btn btn-primary" style={{ padding: "11px 22px" }}>
              Continue exploring
            </Link>
            <Link to="/demo/compare" className="btn btn-secondary" style={{ padding: "11px 22px" }}>
              Open compare lab
            </Link>
          </div>
          {order ? (
            <p className="mono" style={{ margin: "var(--space-6) 0 0", fontSize: 12, color: "var(--ink-2)" }}>
              purchase events: {order.lines.length} sent · {order.acceptedCount} accepted · {order.duplicateCount} duplicate · {order.rejectedCount} rejected
            </p>
          ) : (
            <p style={{ margin: "var(--space-6) 0 0", fontSize: 12, color: "var(--ink-2)" }}>The receipt for this order is no longer in this tab. The purchase events were recorded when it was placed.</p>
          )}
        </div>

        {order && (
          <div className="card elev-sm" style={{ background: "var(--color-surface)", padding: "var(--space-6)", gap: "var(--space-3)" }}>
            <h2 style={{ fontSize: 20, margin: "0 0 var(--space-2)" }}>Order summary</h2>
            {order.lines.map((line) => (
              <div key={line.eventId} className="fct-order-line">
                <span style={{ minWidth: 0 }}>
                  {line.title}
                  <span style={{ color: "var(--ink-2)" }}> × {line.quantity}</span>
                </span>
                <span style={{ whiteSpace: "nowrap" }}>{money(line.lineTotal)}</span>
              </div>
            ))}
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 17, fontFamily: "var(--font-heading)", paddingTop: "var(--space-2)" }}>
              <span>Total</span>
              <span>{money(order.total)}</span>
            </div>
          </div>
        )}
      </section>

      <div style={{ marginTop: "var(--space-8)" }}>
        <Shelf shelf={shelf} surface="order" variant="continue" headingSize={28} noAdd />
      </div>
    </main>
  );
}
