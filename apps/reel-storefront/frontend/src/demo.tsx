import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, isUnavailable } from "./api";
import type { Film, Receipt, Recs, Session, Unavailable } from "./types";

/** Per-viewer UI preferences; storage can be unavailable (private mode), so never depend on it. */
function readPref(key: string, fallback: boolean): boolean {
  try { const v = window.localStorage.getItem(`reel.${key}`); return v === null ? fallback : v === "1"; } catch { return fallback; }
}
function writePref(key: string, value: boolean): void {
  try { window.localStorage.setItem(`reel.${key}`, value ? "1" : "0"); } catch { /* ignore */ }
}

export type Tab = "sequence" | "changes" | "trace" | "status" | "proof";

interface DemoState {
  session: Session | null;
  home: Recs | Unavailable | null;
  homeLoading: boolean;
  receipts: Receipt[];
  insightOpen: boolean;
  tab: Tab;
  autoRefresh: boolean;
  pendingSinceRefresh: number;
  /** Bumped whenever an event is recorded, so the drawer refetches the sequence. */
  version: number;
  toast: string | null;
  lastTrace: Recs | null;
  /** The shopper's films, newest first (training history + live events), and their ids for quick lookup. */
  history: Film[];
  watchedIds: Set<string>;
  switchPersona: (key: string, carry: boolean) => Promise<void>;
  refreshHome: () => Promise<void>;
  watch: (filmId: string, from?: { requestId: string; position: number }) => Promise<Receipt>;
  replay: () => Promise<void>;
  setInsight: (open: boolean, tab?: Tab) => void;
  setAutoRefresh: (on: boolean) => void;
  notify: (message: string) => void;
  setLastTrace: (r: Recs) => void;
}

const Ctx = createContext<DemoState | null>(null);

export function DemoProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [home, setHome] = useState<Recs | Unavailable | null>(null);
  const [homeLoading, setHomeLoading] = useState(false);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [insightOpen, setInsightOpen] = useState(() => readPref("insight", false));
  const [tab, setTab] = useState<Tab>("sequence");
  const [autoRefresh, setAutoRefreshState] = useState(() => readPref("autoUpdate", true));
  const setAutoRefresh = useCallback((on: boolean) => { setAutoRefreshState(on); writePref("autoUpdate", on); }, []);
  const [history, setHistory] = useState<Film[]>([]);
  const [pending, setPending] = useState(0);
  const [version, setVersion] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const [lastTrace, setLastTrace] = useState<Recs | null>(null);

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast((t) => (t === message ? null : t)), 4200);
  }, []);

  const refreshHome = useCallback(async () => {
    setHomeLoading(true);
    try {
      const r = await api.recommend("home");
      setHome(r);
      if (!isUnavailable(r)) setLastTrace(r);
      setPending(0);
    } catch (e) {
      setHome({ available: false, reason: (e as Error).message });
    } finally {
      setHomeLoading(false);
    }
  }, []);

  useEffect(() => {
    api.session().then(setSession).then(refreshHome).catch((e) => notify((e as Error).message));
  }, [refreshHome, notify]);

  // Refetch the shopper's history whenever it can have changed (persona switch, new event).
  useEffect(() => {
    if (!session) return;
    let live = true;
    api.history()
      .then((films) => { if (live) setHistory(films); })
      .catch(() => { if (live) setHistory([]); });
    return () => { live = false; };
  }, [session, version]);
  const watchedIds = useMemo(() => new Set(history.map((f) => f.id)), [history]);

  const switchPersona = useCallback(async (key: string, carry: boolean) => {
    const { session: s, carried } = await api.setPersona(key, carry);
    setSession(s);
    if (carried.length) {
      setReceipts((r) => [...carried.slice().reverse(), ...r].slice(0, 12));
      notify(`Signed in as ${s.persona.name}; ${carried.length} session film(s) recorded to their history.`);
    }
    setVersion((v) => v + 1);
    await refreshHome();
  }, [refreshHome, notify]);

  const watch = useCallback(async (filmId: string, from?: { requestId: string; position: number }) => {
    const receipt = await api.watch(filmId, from);
    setReceipts((r) => [receipt, ...r].slice(0, 12));
    setVersion((v) => v + 1);
    setPending((p) => p + 1);
    if (autoRefresh) {
      await refreshHome();
      notify(receipt.duplicate ? "Already in your history." : "Added to your history. Your picks have been updated.");
    } else {
      notify("Added to your history. Press “Update picks” on Home to see new recommendations.");
    }
    return receipt;
  }, [autoRefresh, refreshHome, notify]);

  const replay = useCallback(async () => {
    try {
      const receipt = await api.replay();
      setReceipts((r) => [receipt, ...r].slice(0, 12));
      notify(receipt.duplicate ? "Same event id sent again: GraphRec answered duplicate, nothing changed." : "Replay was accepted.");
    } catch (e) {
      notify((e as Error).message);
    }
  }, [notify]);

  const value = useMemo<DemoState>(() => ({
    session, home, homeLoading, receipts, insightOpen, tab, autoRefresh, pendingSinceRefresh: pending, version, toast, lastTrace,
    history, watchedIds,
    switchPersona, refreshHome, watch, replay, notify, setAutoRefresh, setLastTrace,
    setInsight: (open, t) => { setInsightOpen(open); writePref("insight", open); if (t) setTab(t); },
  }), [session, home, homeLoading, receipts, insightOpen, tab, autoRefresh, pending, version, toast, lastTrace,
       history, watchedIds, switchPersona, refreshHome, watch, replay, notify, setAutoRefresh]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useDemo(): DemoState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useDemo outside DemoProvider");
  return v;
}

export const strategyLabel = (s: string) =>
  s === "personalized" ? "Picked for you"
  : s === "session" ? "Based on what you just watched"
  : s.includes("fallback") ? "Popular picks" : s;

/** The technical name, shown as a tooltip and in the Insight drawer. */
export const strategyDetail = (s: string) =>
  s === "personalized" ? "Personalized: DGSR scored this shopper's own interaction graph"
  : s === "session" ? "Session approximation: DGSR scored the films from this visit"
  : s.includes("fallback") ? "Fallback: popular films, because GraphRec knows nothing about this visitor yet" : s;
