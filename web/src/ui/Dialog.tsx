import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { describeError } from "../api/client";
import { useToast } from "../hooks/useToast";

interface ModalProps { title: string; width?: number; children: ReactNode; onClose?: () => void; busy?: boolean }
/** One focus/scroll contract for confirmations and one-time secret disclosure. */
function Modal({ title, width = 480, children, onClose, busy }: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = useRef(onClose);
  close.current = busy ? undefined : onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    const shells = Array.from(document.querySelectorAll<HTMLElement>('.shell'));
    const inert = shells.map(shell => shell.inert);
    shells.forEach(shell => { shell.inert = true; });
    document.body.style.overflow = 'hidden';
    ref.current?.querySelector<HTMLElement>('input:not(:disabled),select:not(:disabled),textarea:not(:disabled),button:not(:disabled)')?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close.current?.(); }
      if (event.key !== 'Tab' || !ref.current) return;
      const nodes = Array.from(ref.current.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]'));
      const first = nodes[0]; const last = nodes[nodes.length - 1];
      if (!first) { event.preventDefault(); ref.current.focus(); return; }
      if (!ref.current.contains(document.activeElement) || (!event.shiftKey && document.activeElement === last)) { event.preventDefault(); first.focus(); }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => {
      document.removeEventListener('keydown', keydown);
      document.body.style.overflow = overflow;
      shells.forEach((shell, i) => { shell.inert = inert[i]; });
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return createPortal(<div className="dialog-backdrop" onClick={() => close.current?.()}>
    <div className="dialog" role="dialog" tabIndex={-1} aria-modal="true" aria-labelledby={titleId} aria-busy={busy || undefined} style={{ width: `min(${width}px, 100%)` }} onClick={e => e.stopPropagation()} ref={ref}>
      <h2 className="dialog-title" id={titleId}>{title}</h2>{children}
    </div>
  </div>, document.body);
}
export interface DialogProps {
  title: string; body: ReactNode; consequence?: ReactNode;
  facts?: { label: string; value: ReactNode }[]; width?: number;
  cancelLabel?: string; confirmLabel?: string;
  onConfirm: () => Promise<string | void> | string | void;
  onClose: () => void; children?: ReactNode; confirmDisabled?: boolean;
}
export function Dialog({ title, body, consequence, facts, width, cancelLabel = "Cancel", confirmLabel = "Confirm", onConfirm, onClose, children, confirmDisabled }: DialogProps) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  async function confirm() {
    if (pending.current || confirmDisabled) return;
    pending.current = true; setBusy(true); setError(null);
    try { const result = await onConfirm(); if (typeof result === 'string') setError(result); }
    catch (caught) { setError(describeError(caught)); }
    finally { pending.current = false; setBusy(false); }
  }
  return <Modal title={title} width={width} onClose={onClose} busy={busy}>
    <div className="dialog-body"><p>{body}</p>{consequence ? <p>{consequence}</p> : null}
      {facts?.length ? <dl className="dialog-dl">{facts.map(f => <div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}</dl> : null}
      {children ? <fieldset disabled={busy} className="dialog-fields">{children}</fieldset> : null}
      {error ? <div className="dialog-error" role="alert">{error}</div> : null}
      {busy ? <p role="status">Waiting for GraphRec to confirm the operation…</p> : null}
    </div>
    <div className="dialog-actions"><button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>{cancelLabel}</button><button type="button" className="btn btn-primary" onClick={() => void confirm()} disabled={busy || confirmDisabled}>{busy ? 'Working…' : confirmLabel}</button></div>
  </Modal>;
}
export function SecretDialog({ title, secret, prefix, scopes, onClose }: { title: string; secret: string; prefix: string; scopes: string; onClose: () => void }) {
  const { copy } = useToast();
  return <Modal title={title} width={560}>
    <div className="secret-warn">Save this secret now. It cannot be shown again; rotate the credential if it is lost.</div>
    <pre className="secret-value" data-testid="secret-value">{secret}</pre>
    <div className="secret-meta"><span>Prefix <b className="mono">{prefix}</b></span><span>Scopes {scopes}</span></div>
    <div className="dialog-actions"><button type="button" className="btn btn-secondary" onClick={() => copy(secret)}>Copy secret</button><button type="button" className="btn btn-primary" onClick={onClose}>I have stored it</button></div>
  </Modal>;
}
