import { useSearchParams } from "react-router-dom";

/** Clear related filters in one navigation; router updates are not queued. */
export function useClearQuery() {
  const [, setParams] = useSearchParams();
  return (...keys: string[]) => setParams(previous => {
    const next = new URLSearchParams(previous);
    keys.forEach(key => next.delete(key));
    return next;
  }, { replace: true });
}

/** Shareable URL state for filters and tabs. Preserve unrelated parameters. */
export function useQueryState(key: string, fallback: string): [string, (value: string) => void] {
  const [params, setParams] = useSearchParams();
  return [params.get(key) ?? fallback, value => setParams(previous => {
    const next = new URLSearchParams(previous);
    if (value === fallback || !value) next.delete(key); else next.set(key, value);
    return next;
  }, { replace: true })];
}
