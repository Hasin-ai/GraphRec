import { useCallback, useEffect, useRef, useState } from "react";
import { api, isUnavailable } from "./api";
import { useStore } from "./store";
import type { Recommendations, Surface } from "./types";

export type ShelfPhase = "loading" | "ok" | "empty" | "error";

export interface ShelfState {
  phase: ShelfPhase;
  data: Recommendations | null;
  error: { reason: string; correlationId: string | null } | null;
  retry: () => void;
}

/**
 * One Top-N request for the current shopper. Re-runs when the persona or the
 * exclusion set changes; the page itself never blocks on it.
 */
export function useRecommendations(options: { topN: number; exclude: string[]; surface: Surface; enabled?: boolean }): ShelfState {
  const { session, isGuest, recentProductIds, setLastProvenance } = useStore();
  const [phase, setPhase] = useState<ShelfPhase>("loading");
  const [data, setData] = useState<Recommendations | null>(null);
  const [error, setError] = useState<ShelfState["error"]>(null);
  const [nonce, setNonce] = useState(0);
  const generation = useRef(0);
  const excludeKey = [...options.exclude].sort().join("|");
  const personaKey = session?.persona.key;
  const enabled = options.enabled ?? true;

  useEffect(() => {
    if (!personaKey || !enabled) return;
    const current = (generation.current += 1);
    setPhase("loading");
    api
      .recommendations({
        topN: options.topN,
        excludeProductIds: excludeKey ? excludeKey.split("|") : [],
        recentProductIds: isGuest ? recentProductIds : undefined,
        surface: options.surface,
      })
      .then((result) => {
        if (current !== generation.current) return;
        if (isUnavailable(result)) {
          setError({ reason: result.reason, correlationId: result.correlationId });
          setData(null);
          setPhase("error");
          return;
        }
        setData(result);
        setError(null);
        setLastProvenance(result.provenance);
        setPhase(result.items.length ? "ok" : "empty");
      })
      .catch((e: Error & { correlationId?: string }) => {
        if (current !== generation.current) return;
        setError({ reason: e.message, correlationId: e.correlationId ?? null });
        setData(null);
        setPhase("error");
      });
    // recentProductIds is deliberately not a dependency: it only seeds the next request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personaKey, excludeKey, options.topN, options.surface, nonce, enabled]);

  const retry = useCallback(() => setNonce((n) => n + 1), []);
  return { phase, data, error, retry };
}
