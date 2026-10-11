import { useStore } from "../lib/store";

export function Toast() {
  const { toast, dismissToast } = useStore();
  if (!toast) return null;
  const dot = toast.kind === "warn" ? "var(--preview)" : toast.kind === "ok" ? "var(--verified)" : "var(--ink-2)";
  return (
    <div role="status" className={`fct-toast elev-lg fct-rise ${toast.kind === "warn" ? "warn" : ""}`}>
      <span aria-hidden="true" className="fct-dot" style={{ background: dot }} />
      <span className="msg">{toast.message}</span>
      <button
        type="button"
        className="btn btn-ghost"
        style={{ fontSize: 12, whiteSpace: "nowrap" }}
        onClick={() => {
          toast.action?.run();
          dismissToast();
        }}
      >
        {toast.action?.label ?? "Dismiss"}
      </button>
    </div>
  );
}
