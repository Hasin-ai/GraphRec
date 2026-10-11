/** App-wide state: the demo session, the persona-scoped cart, and UI chrome (drawer, rail, toast). */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { addLine, cartCount, changeQty, loadCart, removeLine, saveCart, type CartLine } from "./cart";
import type { Health, Persona, Product, Provenance, Session } from "./types";

export interface Toast {
  message: string;
  kind: "ok" | "warn" | "note";
  action?: { label: string; run: () => void };
}

interface Store {
  session: Session | null;
  sessionError: string | null;
  persona: Persona | null;
  isGuest: boolean;
  switchPersona: (key: string) => Promise<void>;
  switching: boolean;

  cart: CartLine[];
  count: number;
  addToCart: (product: Product, qty?: number) => void;
  setQty: (productId: string, delta: number) => void;
  removeFromCart: (productId: string) => void;
  clearCart: () => void;

  drawerOpen: boolean;
  setDrawerOpen: (open: boolean) => void;
  railOpen: boolean;
  setRailOpen: (open: boolean) => void;
  toast: Toast | null;
  showToast: (toast: Toast) => void;
  dismissToast: () => void;
  live: string;
  announce: (message: string) => void;

  recentProductIds: string[];
  noteViewed: (productId: string) => void;
  lastProvenance: Provenance | null;
  setLastProvenance: (prov: Provenance | null) => void;
  health: Health | null;
  refreshHealth: () => Promise<void>;
}

const StoreContext = createContext<Store | null>(null);

const RECENT_KEY = "facet:recent";

function loadRecent(): string[] {
  try {
    const raw = sessionStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [live, setLive] = useState("");
  const [recentProductIds, setRecent] = useState<string[]>(loadRecent);
  const [lastProvenance, setLastProvenance] = useState<Provenance | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const personaKey = session?.persona.key ?? null;

  useEffect(() => {
    api
      .session()
      .then((s) => {
        setSession(s);
        setSessionError(null);
      })
      .catch((error: Error) => setSessionError(error.message));
  }, []);

  // The cart follows the persona: switching shoppers swaps the namespace.
  useEffect(() => {
    if (personaKey) setCart(loadCart(personaKey));
  }, [personaKey]);

  useEffect(() => {
    if (personaKey) saveCart(personaKey, cart);
  }, [cart, personaKey]);

  const announce = useCallback((message: string) => setLive(message), []);

  const showToast = useCallback((next: Toast) => {
    setToast(next);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3600);
  }, []);
  const dismissToast = useCallback(() => setToast(null), []);

  const switchPersona = useCallback(
    async (key: string) => {
      setSwitching(true);
      try {
        const next = await api.setPersona(key);
        setSession(next);
        setLastProvenance(null);
        announce(`Switched to ${next.persona.name}. Recommendations reloading.`);
      } catch (error) {
        showToast({ message: `Could not switch shopper: ${(error as Error).message}`, kind: "warn" });
      } finally {
        setSwitching(false);
      }
    },
    [announce, showToast],
  );

  const addToCart = useCallback(
    (product: Product, qty = 1) => {
      if (!session) return;
      setCart((lines) => {
        const next = addLine(lines, product, qty);
        announce(`${product.title} added. Cart has ${cartCount(next)} items.`);
        return next;
      });
      void api.event({ action: "add_to_cart", productId: product.externalId, quantity: qty, price: product.price, surface: "cart" }).then((ok) => {
        if (!ok) showToast({ message: "Could not record that cart event. Shopping is unaffected.", kind: "warn" });
      });
      showToast({ message: `${product.title} added to ${session.persona.name}'s cart`, kind: "ok", action: { label: "View cart", run: () => setDrawerOpen(true) } });
    },
    [announce, session, showToast],
  );

  const setQty = useCallback((productId: string, delta: number) => {
    setCart((lines) => {
      const before = lines.find((l) => l.product.externalId === productId);
      const next = changeQty(lines, productId, delta);
      if (before && delta < 0 && before.qty + delta <= 0) void api.event({ action: "remove_from_cart", productId, quantity: before.qty, surface: "cart" });
      return next;
    });
  }, []);

  const removeFromCart = useCallback((productId: string) => {
    setCart((lines) => {
      const before = lines.find((l) => l.product.externalId === productId);
      if (before) void api.event({ action: "remove_from_cart", productId, quantity: before.qty, surface: "cart" });
      return removeLine(lines, productId);
    });
  }, []);

  const clearCart = useCallback(() => setCart([]), []);

  const noteViewed = useCallback((productId: string) => {
    setRecent((ids) => {
      const next = [...ids.filter((i) => i !== productId), productId].slice(-10);
      try {
        sessionStorage.setItem(RECENT_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
    } catch {
      setHealth(null);
    }
  }, []);

  const value = useMemo<Store>(
    () => ({
      session,
      sessionError,
      persona: session?.persona ?? null,
      isGuest: !session?.persona.userId,
      switchPersona,
      switching,
      cart,
      count: cartCount(cart),
      addToCart,
      setQty,
      removeFromCart,
      clearCart,
      drawerOpen,
      setDrawerOpen,
      railOpen,
      setRailOpen,
      toast,
      showToast,
      dismissToast,
      live,
      announce,
      recentProductIds,
      noteViewed,
      lastProvenance,
      setLastProvenance,
      health,
      refreshHealth,
    }),
    [session, sessionError, switchPersona, switching, cart, addToCart, setQty, removeFromCart, clearCart, drawerOpen, railOpen, toast, showToast, dismissToast, live, announce, recentProductIds, noteViewed, lastProvenance, health, refreshHealth],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): Store {
  const store = useContext(StoreContext);
  if (!store) throw new Error("useStore must be used inside StoreProvider");
  return store;
}
