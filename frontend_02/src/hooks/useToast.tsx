import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

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

  const flash = useCallback((message: string, tone: "ok" | "danger" = "ok") => {
    setToast({ message, tone });
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setToast(null), 2600);
  }, []);

  const copy = useCallback(
    (text: string) => {
      try {
        void navigator.clipboard?.writeText(String(text));
      } catch {
        /* clipboard unavailable */
      }
      flash("Copied to clipboard.");
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
