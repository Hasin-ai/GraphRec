import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { describeError } from "../api/client";
import { useToast } from "../hooks/useToast";

export interface DialogProps {
  title: string;
  body: ReactNode;
  consequence?: ReactNode;
  /** Facts the user should review before confirming, in a compact grid. */
  facts?: { label: string; value: ReactNode }[];
  width?: number;
  cancelLabel?: string;
  confirmLabel?: string;
  /** Return a string to keep the dialog open with an inline error; throw to show the API failure. */
  onConfirm: () => Promise<string | void> | string | void;
  onClose: () => void;
  children?: ReactNode;
  confirmDisabled?: boolean;
}

/**
 * Modal confirmation with focus trapping, Escape and backdrop dismissal. Every
 * destructive or state-changing action in the console goes through this.
 */
export function Dialog({ title, body, consequence, facts, width = 480, cancelLabel = "Cancel", confirmLabel = "Confirm", onConfirm, onClose, children, confirmDisabled }: DialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const first = ref.current?.querySelector<HTMLElement>("input,select,textarea,button");
    first?.focus();
  }, []);

  function keys(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") onClose();
    if (event.key === "Tab" && ref.current) {
      const nodes = ref.current.querySelectorAll<HTMLElement>("button,input,select,textarea,a[href]");
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const result = await onConfirm();
      if (typeof result === "string") setError(result);
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-backdrop" style={{ zIndex: 80 }} onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" style={{ width: `min(${width}px, 100%)` }} onClick={(e) => e.stopPropagation()} ref={ref} onKeyDown={keys}>
        <div className="dialog-title" id="dialog-title">
          {title}
        </div>
        <div className="dialog-body">
          <p>{body}</p>
          {consequence ? <p style={{ color: "var(--color-neutral-800)" }}>{consequence}</p> : null}
          {facts && facts.length ? (
            <dl className="dialog-dl">
              {facts.map((f) => (
                <div key={f.label}>
                  <dt>{f.label}</dt>
                  <dd>{f.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {children ? <div className="dialog-fields">{children}</div> : null}
          {error ? (
            <div className="dialog-error" role="alert">
              {error}
            </div>
          ) : null}
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
            {cancelLabel}
          </button>
          <button type="button" className="btn btn-primary" onClick={() => void confirm()} disabled={busy || confirmDisabled}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** One-time secret display: shown once, not re-openable, with an explicit acknowledgement. */
export function SecretDialog({ title, secret, prefix, scopes, onClose }: { title: string; secret: string; prefix: string; scopes: string; onClose: () => void }) {
  const { copy } = useToast();
  return (
    <div className="dialog-backdrop" style={{ zIndex: 90 }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="secret-title" style={{ width: "min(560px, 100%)" }}>
        <div className="dialog-title" id="secret-title">
          {title}
        </div>
        <div className="secret-warn">This value is shown once. GraphRec does not retain it. If it is lost, rotate the credential to obtain a new one.</div>
        <pre className="secret-value" data-testid="secret-value">
          {secret}
        </pre>
        <div className="secret-meta">
          <span>
            Prefix <b className="mono">{prefix}</b>
          </span>
          <span>Scopes {scopes}</span>
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={() => copy(secret)}>
            Copy secret
          </button>
          <button type="button" className="btn btn-primary" onClick={onClose}>
            I have stored it
          </button>
        </div>
      </div>
    </div>
  );
}
