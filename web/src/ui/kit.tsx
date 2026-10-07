import { useCallback, useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject } from "react";
import { Link } from "react-router-dom";
import { fmtDateTimeFull, fmtRelative } from "../lib/format";
import { Icon, type IconName } from "./icons";

/* ───────────────────────── Button ───────────────────────── */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive";
export type ButtonSize = "sm" | "md";
const VARIANT_CLASS: Record<ButtonVariant, string> = { primary: "btn-primary", secondary: "btn-secondary", ghost: "btn-ghost", destructive: "btn-danger" };
export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", extra?: string) {
  return `btn ${VARIANT_CLASS[variant]}${size === "sm" ? " btn-sm" : ""}${extra ? ` ${extra}` : ""}`;
}
export function Button({ variant = "secondary", size = "md", icon, loading, children, className, ...rest }:
  { variant?: ButtonVariant; size?: ButtonSize; icon?: IconName; loading?: boolean } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" className={buttonClass(variant, size, className)} aria-busy={loading || undefined} {...rest}>
    {icon ? <Icon name={icon} size={size === "sm" ? 14 : 15} className={loading ? "spin" : undefined} /> : null}
    {children}
  </button>;
}
export function ButtonLink({ to, variant = "secondary", size = "md", icon, children }: { to: string; variant?: ButtonVariant; size?: ButtonSize; icon?: IconName; children: ReactNode }) {
  return <Link to={to} className={buttonClass(variant, size)}>{icon ? <Icon name={icon} size={size === "sm" ? 14 : 15} /> : null}{children}</Link>;
}

/* ───────────────────────── Status ───────────────────────── */
export type StatusTone = "success" | "warning" | "danger" | "info" | "neutral";
/** A dot + neutral text. Colour is never the only signal: the label carries the meaning. */
export function StatusDot({ tone, children, title }: { tone: StatusTone; children?: ReactNode; title?: string }) {
  return <span className={`status-dot tone-${tone}`} title={title}><span className="sd" aria-hidden="true" />{children}</span>;
}
export function StatusPill({ tone, icon, children, title }: { tone: StatusTone; icon?: IconName; children: ReactNode; title?: string }) {
  return <span className={`pill tone-${tone}`} title={title}>{icon ? <Icon name={icon} size={12} /> : <span className="sd" aria-hidden="true" />}{children}</span>;
}

/* ───────────────────────── Alert ───────────────────────── */
const ALERT_ICON: Record<StatusTone, IconName> = { danger: "alert-octagon", warning: "alert-triangle", info: "info", success: "check-circle", neutral: "info" };
export function Alert({ tone = "info", title, children, action, compact }: { tone?: StatusTone; title?: ReactNode; children?: ReactNode; action?: ReactNode; compact?: boolean }) {
  return <div className={`alert tone-${tone}${compact ? " compact" : ""}`} role={tone === "danger" ? "alert" : "status"}>
    <Icon name={ALERT_ICON[tone]} size={18} className="alert-icon" />
    <div className="alert-text">{title ? <div className="alert-title">{title}</div> : null}{children ? <div className="alert-body">{children}</div> : null}</div>
    {action ? <div className="alert-action">{action}</div> : null}
  </div>;
}

/* ───────────────────────── Progress ───────────────────────── */
export function Progress({ value, max, tone = "neutral", label }: { value: number; max: number; tone?: StatusTone; label: string }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : value > 0 ? 100 : 0;
  return <div className={`progress tone-${tone}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label={label}>
    <div className="progress-fill" style={{ width: `${pct}%` }} />
  </div>;
}

/* ───────────────────────── Tooltip / help ───────────────────────── */
/** Lightweight tooltip: visible on hover and keyboard focus, announced via aria-describedby. */
export function Tooltip({ content, children }: { content: ReactNode; children: ReactNode }) {
  const id = useId();
  return <span className="tt" aria-describedby={id}>{children}<span role="tooltip" id={id} className="tt-bubble">{content}</span></span>;
}
export function HelpTip({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return <span className="tt"><button type="button" className="help-tip" aria-label={`About ${label}`} aria-describedby={id}><Icon name="help-circle" size={13} /></button><span role="tooltip" id={id} className="tt-bubble">{children}</span></span>;
}
/** Relative time with the absolute date in a tooltip ("23 days ago" · Sep 12, 2026 11:29 PM). */
export function RelativeTime({ value }: { value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return <span className="muted">—</span>;
  const iso = new Date(value).toISOString();
  return <time dateTime={iso} title={fmtDateTimeFull(value)}>{fmtRelative(value)}</time>;
}

/* ───────────────────────── Popover / menu ───────────────────────── */
/** Click-outside + Escape handling for a disclosure. Focus returns to the trigger on Escape. */
export function usePopover<T extends HTMLElement>(): { open: boolean; setOpen: (v: boolean) => void; toggle: () => void; ref: RefObject<T | null>; triggerRef: RefObject<HTMLButtonElement | null> } {
  const [open, setOpen] = useState(false);
  const ref = useRef<T | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node) && !triggerRef.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); triggerRef.current?.focus(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const toggle = useCallback(() => setOpen(o => !o), []);
  return { open, setOpen, toggle, ref, triggerRef };
}
/** Arrow-key roving focus inside a menu. */
export function menuKeys(e: ReactKeyboardEvent<HTMLElement>) {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
  const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"],[role="menuitemradio"]')).filter(el => !(el as HTMLButtonElement).disabled);
  if (!items.length) return;
  e.preventDefault();
  const i = items.indexOf(document.activeElement as HTMLElement);
  const next = e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
  items[next].focus();
}

export interface MenuItem { label: string; icon?: IconName; onSelect?: () => void; to?: string; danger?: boolean; disabled?: boolean; hint?: string }
/** Overflow ("…") menu for table rows. */
export function OverflowMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const pop = usePopover<HTMLDivElement>();
  useEffect(() => { if (pop.open) pop.ref.current?.querySelector<HTMLElement>('[role="menuitem"]:not(:disabled)')?.focus(); }, [pop.open, pop.ref]);
  return <div className="menu-wrap">
    <button ref={pop.triggerRef} type="button" className="icon-button" aria-label={label} aria-haspopup="menu" aria-expanded={pop.open} onClick={pop.toggle}><Icon name="more-horizontal" /></button>
    {pop.open ? <div ref={pop.ref} className="menu" role="menu" aria-label={label} onKeyDown={menuKeys}>
      {items.map(item => item.to && !item.disabled
        ? <Link key={item.label} role="menuitem" className={`menu-item${item.danger ? " danger" : ""}`} to={item.to} onClick={() => pop.setOpen(false)}>{item.icon ? <Icon name={item.icon} size={15} /> : null}{item.label}</Link>
        : <button key={item.label} type="button" role="menuitem" className={`menu-item${item.danger ? " danger" : ""}`} disabled={item.disabled} title={item.hint}
          onClick={() => { pop.setOpen(false); item.onSelect?.(); }}>{item.icon ? <Icon name={item.icon} size={15} /> : null}{item.label}</button>)}
    </div> : null}
  </div>;
}

/* ───────────────────────── Card / section ───────────────────────── */
export function Card({ title, description, actions, children, flush, className }: { title?: ReactNode; description?: ReactNode; actions?: ReactNode; children?: ReactNode; flush?: boolean; className?: string }) {
  return <section className={`card${flush ? " flush" : ""}${className ? ` ${className}` : ""}`}>
    {title || actions ? <header className="card-head"><div><h2 className="card-title">{title}</h2>{description ? <p className="card-desc">{description}</p> : null}</div>{actions ? <div className="card-actions">{actions}</div> : null}</header> : null}
    {children}
  </section>;
}
export function SectionHeader({ title, description, aside, id }: { title: string; description?: ReactNode; aside?: ReactNode; id?: string }) {
  return <div className="section-head"><div><h2 id={id}>{title}</h2>{description ? <p>{description}</p> : null}</div>{aside ? <div className="section-aside">{aside}</div> : null}</div>;
}
