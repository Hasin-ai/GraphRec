import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

interface Toast {
  message: string;
  tone: "ok" | "danger";
}

interface ToastContextValue {
  flash: (message: string, tone?: "ok" | "danger") => void;
  copy: (text: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const flash = useCallback((message: string, tone: "ok" | "danger" = "ok") => {
    setToast({ message, tone });
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);

  const copy = useCallback(
    async (text: string) => {
      try {
        if (!navigator.clipboard) throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(String(text));
        flash("Copied to clipboard.");
      } catch {
        flash("Could not copy. Select the value and copy it manually.", "danger");
      }
    },
    [flash],
  );

  const value = useMemo(() => ({ flash, copy }), [flash, copy]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      {toast ? (
        <div role="status" className={`toast ${toast.tone}`}>
          {toast.message}
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}
