import { useCallback, useEffect, useMemo, useRef, useState, type DependencyList } from "react";
import { RESOURCE_CHANGED } from "../api/client";
import { useSession } from "./useSession";

export interface Resource<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => Promise<void>;
  setData: (updater: T | ((previous: T | null) => T | null)) => void;
  loadedAt: number | null;
}
interface Options { watch?: string[]; pollMs?: number }

/** Session-owned data: a changed identity or parameter never exposes the old result. */
export function useResource<T>(loader: () => Promise<T>, deps: DependencyList = [], options: Options = {}): Resource<T> {
  const { tenant, platform } = useSession();
  const identity = useMemo(() => ({}), [tenant?.accessToken, platform?.token, ...deps]);
  const current = useRef(identity);
  current.current = identity;
  const latestLoader = useRef(loader);
  latestLoader.current = loader;
  const generation = useRef(0);
  const mounted = useRef(false);
  const [state, setState] = useState<{ identity: object; data: T | null; error: unknown; loading: boolean; loadedAt: number | null }>({ identity, data: null, error: null, loading: true, loadedAt: null });

  const run = useCallback(async () => {
    if (!mounted.current || current.current !== identity) return;
    const mine = ++generation.current;
    setState(previous => previous.identity === identity ? { ...previous, loading: true } : { identity, data: null, error: null, loading: true, loadedAt: null });
    try {
      const result = await latestLoader.current();
      if (mounted.current && mine === generation.current && current.current === identity) setState({ identity, data: result, error: null, loading: false, loadedAt: Date.now() });
    } catch (error) {
      if (mounted.current && mine === generation.current && current.current === identity) setState(previous => ({ ...previous, error, loading: false }));
    }
  }, [identity]);

  const watches = options.watch?.join("|") ?? "";
  useEffect(() => {
    mounted.current = true;
    void run();
    const changed = (event: Event) => {
      const path = (event as CustomEvent<string>).detail;
      if (watches && watches.split("|").some(fragment => path.includes(fragment))) void run();
    };
    window.addEventListener(RESOURCE_CHANGED, changed);
    return () => {
      mounted.current = false;
      generation.current += 1;
      window.removeEventListener(RESOURCE_CHANGED, changed);
    };
  }, [run, watches]);

  useEffect(() => {
    if (!options.pollMs) return;
    const timer = window.setInterval(() => { if (!document.hidden) void run(); }, options.pollMs);
    return () => window.clearInterval(timer);
  }, [run, options.pollMs]);

  const setData = useCallback((updater: T | ((previous: T | null) => T | null)) => {
    if (!mounted.current || current.current !== identity) return;
    generation.current += 1;
    setState(previous => ({ identity, error: null, loading: false, loadedAt: Date.now(), data: typeof updater === "function" ? (updater as (p: T | null) => T | null)(previous.identity === identity ? previous.data : null) : updater }));
  }, [identity]);
  return { ...(state.identity === identity ? state : { data: null, error: null, loading: true, loadedAt: null }), reload: run, setData };
}
