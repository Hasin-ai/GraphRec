import { useCallback, useEffect, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
export type ThemeMode = Theme | "system";
const KEY = "graphrec.theme";
const EVENT = "graphrec:theme";

function readMode(): ThemeMode {
  try {
    const stored = window.localStorage.getItem(KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    /* ignore */
  }
  return "system";
}
function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function subscribe(callback: () => void) {
  const media = window.matchMedia?.("(prefers-color-scheme: dark)");
  window.addEventListener(EVENT, callback);
  window.addEventListener("storage", callback);
  media?.addEventListener?.("change", callback);
  return () => {
    window.removeEventListener(EVENT, callback);
    window.removeEventListener("storage", callback);
    media?.removeEventListener?.("change", callback);
  };
}
const snapshot = () => `${readMode()}|${systemTheme()}`;

/**
 * Light / dark / system theme. Returns the resolved theme, a light⇄dark toggle,
 * and the stored mode with its setter (the user menu offers all three).
 */
export function useTheme(): [Theme, () => void, ThemeMode, (mode: ThemeMode) => void] {
  const [mode, sys] = useSyncExternalStore(subscribe, snapshot, () => "system|light").split("|") as [ThemeMode, Theme];
  const theme: Theme = mode === "system" ? sys : mode;
  useEffect(() => { document.documentElement.setAttribute("data-theme", theme); }, [theme]);
  const setMode = useCallback((next: ThemeMode) => {
    try { window.localStorage.setItem(KEY, next); } catch { /* ignore */ }
    window.dispatchEvent(new Event(EVENT));
  }, []);
  const toggle = useCallback(() => setMode(theme === "light" ? "dark" : "light"), [theme, setMode]);
  return [theme, toggle, mode, setMode];
}
