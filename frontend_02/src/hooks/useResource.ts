import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

export interface Resource<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  /** Re-run the loader; keeps the current data visible while it runs. */
  reload: () => Promise<void>;
  /** Replace the data locally (after a mutation) without a round trip. */
  setData: (updater: T | ((previous: T | null) => T | null)) => void;
  loadedAt: number | null;
}

/**
 * Minimal async resource hook: one loader, one state triple, cancellation on
 * unmount or dependency change. Pages compose several of these; there is no
 * global cache because every list here is small and tenant-scoped.
 */
export function useResource<T>(loader: () => Promise<T>, deps: DependencyList = []): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const generation = useRef(0);

  const run = useCallback(async () => {
    const mine = ++generation.current;
    setLoading(true);
    try {
      const result = await loader();
      if (mine !== generation.current) return;
      setData(result);
      setError(null);
      setLoadedAt(Date.now());
    } catch (caught) {
      if (mine !== generation.current) return;
      setError(caught);
    } finally {
      if (mine === generation.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void run();
    return () => {
      generation.current += 1;
    };
  }, [run]);

  const set = useCallback((updater: T | ((previous: T | null) => T | null)) => {
    setData((previous) => (typeof updater === "function" ? (updater as (p: T | null) => T | null)(previous) : updater));
  }, []);

  return { data, error, loading, reload: run, setData: set, loadedAt };
}
