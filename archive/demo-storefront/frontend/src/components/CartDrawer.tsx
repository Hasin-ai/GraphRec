import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { cartSubtotal, newOrderKey } from "../lib/cart";
import { money, swatchStyle } from "../lib/format";
import { useStore } from "../lib/store";

export function CartDrawer() {
  const { drawerOpen, setDrawerOpen, cart, setQty, removeFromCart, clearCart, persona, announce } = useStore();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; correlationId?: string } | null>(null);
  const orderKey = useRef<string | null>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!drawerOpen) return;
    closeBtn.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen, setDrawerOpen]);

  if (!drawerOpen || !persona) return null;

  const subtotal = cartSubtotal(cart);

  const simulate = async () => {
    if (!cart.length) return;
    setBusy(true);
    setError(null);
    // One key per attempt: a retry after a failure produces the same order id and events.
    orderKey.current ??= newOrderKey();
    try {
      const order = await api.purchase({ lines: cart.map((l) => ({ productId: l.product.externalId, quantity: l.qty })), clientOrderKey: orderKey.current });
      orderKey.current = null;
      clearCart(); // only after the server accepted the request
      setDrawerOpen(false);
      announce(`Purchase simulated. Order ${order.orderId}.`);
      navigate(`/order/${order.orderId}`, { state: { order, personaName: persona.name } });
    } catch (e) {
      const err = e as ApiError;
      setError({ message: err.message, correlationId: err.correlationId });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fct-scrim">
      <div className="backdrop" onClick={() => setDrawerOpen(false)} />
      <aside role="dialog" aria-modal="true" aria-label="Cart" className="fct-drawer fct-rise">
        <header>
          <span style={{ display: "flex", flexDirection: "column" }}>
            <span className="fct-kicker">cart · {persona.key}</span>
            <span className="title">Your cart</span>
          </span>
          <button ref={closeBtn} type="button" className="btn btn-icon btn-secondary" onClick={() => setDrawerOpen(false)} aria-label="Close cart">
            ✕
          </button>
        </header>

        <div className="body">
          {cart.length === 0 ? (
            <div style={{ padding: "var(--space-8) 0" }}>
              <div aria-hidden="true" style={{ width: 72, height: 72, borderRadius: "50%", background: "var(--color-accent-100)", marginBottom: "var(--space-4)" }} />
              <p style={{ margin: "0 0 var(--space-2)", fontFamily: "var(--font-heading)", fontSize: 21 }}>Nothing here yet</p>
              <p style={{ margin: "0 0 var(--space-4)", fontSize: 14, color: "var(--ink-2)", maxWidth: "34ch" }}>This cart belongs to {persona.name} only. Switching personas swaps it out.</p>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setDrawerOpen(false);
                  navigate("/");
                }}
              >
                Browse products
              </button>
            </div>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
              {cart.map((line) => (
                <li key={line.product.externalId} className="fct-cart-line">
                  <span aria-hidden="true" className="fct-swatch" style={swatchStyle(line.product.category, 56, line.product.accent)} />
                  <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                    <span className="name">{line.product.title}</span>
                    <span style={{ fontSize: 13, color: "var(--ink-2)" }}>
                      {money(line.product.price)}
                      {line.product.size ? ` · ${line.product.size}` : ""}
                    </span>
                    <span style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                      <span className="fct-stepper small">
                        <button type="button" className="btn btn-icon" onClick={() => setQty(line.product.externalId, -1)} aria-label={`Decrease quantity of ${line.product.title}`}>
                          −
                        </button>
                        <span className="qty">{line.qty}</span>
                        <button type="button" className="btn btn-icon" onClick={() => setQty(line.product.externalId, 1)} aria-label={`Increase quantity of ${line.product.title}`} disabled={line.qty >= 99}>
                          +
                        </button>
                      </span>
                      <button type="button" className="btn btn-ghost" style={{ fontSize: 12 }} onClick={() => removeFromCart(line.product.externalId)}>
                        Remove
                      </button>
                    </span>
                  </span>
                  <span style={{ fontSize: 14, whiteSpace: "nowrap" }}>{money(Number(line.product.price) * line.qty)}</span>
                </li>
              ))}
            </ul>
          )}
          {error && (
            <div className="fct-error" role="alert">
              <p className="title">The purchase could not be recorded</p>
              <p className="body">
                {error.message} Your cart is unchanged.
                {error.correlationId && (
                  <>
                    {" "}
                    Correlation ID <code>{error.correlationId}</code>
                  </>
                )}
              </p>
            </div>
          )}
        </div>

        <footer>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "var(--space-3)" }}>
            <span style={{ fontSize: 14, color: "var(--ink-2)" }}>Subtotal</span>
            <span style={{ fontFamily: "var(--font-heading)", fontSize: 24 }}>{money(subtotal)}</span>
          </div>
          <button type="button" className="btn btn-primary btn-block" style={{ padding: 13, fontSize: 15 }} disabled={!cart.length || busy} onClick={simulate} aria-busy={busy}>
            {busy ? "Recording…" : error ? "Retry simulated purchase" : "Simulate purchase"}
          </button>
          <p style={{ margin: "var(--space-2) 0 0", fontSize: 11, color: "var(--ink-2)", textAlign: "center" }}>No payment is taken. One deterministic purchase event is recorded per line.</p>
        </footer>
      </aside>
    </div>
  );
}
