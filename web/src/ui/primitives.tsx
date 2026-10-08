import type { CSSProperties, ReactNode } from "react";
import { describeError, isApiError } from "../api/client";
import { useToast } from "../hooks/useToast";
import { toneFor, type Tone } from "../lib/status";
import { quotaState } from "../lib/quota";
import { isCodeLike, STATUS_HELP } from "../lib/labels";

const REFRESH_SVG = <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;

const TONE_STYLE: Record<Tone, CSSProperties> = {
  ok: { background: "var(--ok-bg)", color: "var(--ok)" },
  warn: { background: "var(--warn-bg)", color: "var(--warn)" },
  danger: { background: "var(--danger-bg)", color: "var(--danger)" },
  info: { background: "var(--info-bg)", color: "var(--info)" },
  neu: { background: "var(--neu-bg)", color: "var(--neu)" },
};

// ── tags ───────────────────────────────────────────────────────
export function Tag({
  tone = "neu",
  mono,
  dot,
  children,
}: {
  tone?: Tone;
  mono?: boolean;
  /** Leading status dot. Used by Badge so a state reads at a glance, not only by hue. */
  dot?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`tag${mono ? " mono" : ""}`} style={TONE_STYLE[tone]}>
      {dot ? <span className="dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

/** A state badge: the value in mono, with its fixed semantic colour and a status dot. */
/** Display labels where the API vocabulary isn't what an operator thinks in. */
const BADGE_LABEL: Record<string, Record<string, string>> = { model: { active: "Serving", retired: "Available", eligible: "Available", archived: "Archived" } };
const COMPLETION_GROUPS = new Set(["job", "outcome", "batch"]);
/**
 * A state badge with a shape that matches its meaning: completed work gets a
 * check or cross, live states (serving, keys, tenants) get a status dot.
 */
export function Badge({ group, value: raw }: { group: string; value: string }) {
  const value = String(raw ?? "unknown");
  const tone = toneFor(group, value);
  const kind = COMPLETION_GROUPS.has(group) && (tone === "ok" || tone === "danger") ? (tone === "ok" ? "check" : "cross") : (tone === "info" && (value === "running" || value === "queued")) ? "spin" : "dot";
  return (
    <span className={`tag badge badge-${tone} badge-${kind}${BADGE_LABEL[group]?.[value] ? " no-cap" : ""}`} data-value={value} title={STATUS_HELP[group]?.[value]}>
      {kind === "check" ? <svg aria-hidden="true" viewBox="0 0 16 16" width="12" height="12"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
        : kind === "cross" ? <svg aria-hidden="true" viewBox="0 0 16 16" width="12" height="12"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
        : <span className="dot" aria-hidden="true" />}
      {BADGE_LABEL[group]?.[value] ?? value.replace(/_/g, " ")}
    </span>
  );
}

/**
 * A copyable identifier (audit X-6/X-7): shortened, monospace, copies the full
 * value on click. Replaces "value + [Copy]" button pairs everywhere.
 */
export function IdChip({ value, display, length = 12, label = "ID" }: { value: string; display?: string; length?: number; label?: string }) {
  const { copy } = useToast();
  const shown = display ?? (value.length > length + 1 ? `${value.slice(0, length)}…` : value);
  return <button type="button" className="id-chip" title={`Copy ${label.toLowerCase()}: ${value}`} aria-label={`Copy ${label.toLowerCase()} ${value}`} onClick={() => copy(value)}>
    <span>{shown}</span>
    <svg aria-hidden="true" viewBox="0 0 16 16" width="12" height="12"><rect x="5" y="5" width="8.5" height="8.5" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M10.5 3.5V3A1.5 1.5 0 0 0 9 1.5H3A1.5 1.5 0 0 0 1.5 3v6A1.5 1.5 0 0 0 3 10.5h.5" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
  </button>;
}

/** One-line legend explaining a status vocabulary (audit X-5). */
export function StatusLegend({ group, values }: { group: string; values: string[] }) {
  return <dl className="status-legend">{values.map(v => <div key={v}><dt><span className={`badge badge-${toneFor(group, v)} badge-dot legend-badge`}><span className="dot" aria-hidden="true" />{BADGE_LABEL[group]?.[v] ?? v.replace(/_/g, " ")}</span></dt><dd>{STATUS_HELP[group]?.[v] ?? ""}</dd></div>)}</dl>;
}

// ── meter ──────────────────────────────────────────────────────
/**
 * A measured quantity against its limit. `limit` of null means the dimension is
 * informational: the track renders at rest rather than implying a full bar.
 */
export function Meter({
  used,
  limit,
  caption,
}: {
  used: number;
  limit: number | null;
  caption?: ReactNode;
}) {
  const quota = quotaState(used, limit);
  const fraction = Math.max(0, Math.min(1, quota.ratio ?? 0));
  const tone = quota.tone;
  if (limit === null || limit === 0) return <span className={`meter ${tone}`}><span className="cap">{caption ?? quota.label}</span></span>;
  return (
    <div
      className={`meter ${tone}`}
      role="meter"
      aria-valuenow={Math.min(limit, Math.max(0, used))}
      aria-valuemin={0}
      aria-valuemax={limit}
      aria-valuetext={`${used} of ${limit}. ${quota.label}`}
      aria-label={typeof caption === "string" ? caption : "Quota usage"}
    >
      <div className="track">
        <div className="fill" style={{ width: `${fraction * 100}%` }} />
      </div>
      {caption ? <span className="cap">{caption}</span> : null}
    </div>
  );
}

// ── banners ────────────────────────────────────────────────────
export function Banner({
  tone = "info",
  title,
  children,
  onDismiss,
}: {
  tone?: Tone;
  title: string;
  children?: ReactNode;
  onDismiss?: () => void;
}) {
  return (
    <div className={`banner ${tone}`} role={tone === "danger" ? "alert" : "status"}>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div className="b-title">{title}</div>
        {children ? <div className="b-body">{children}</div> : null}
      </div>
      {onDismiss ? (
        <button type="button" className="btn btn-secondary btn-sm" style={{ alignSelf: "flex-start" }} onClick={onDismiss}>
          Dismiss
        </button>
      ) : null}
    </div>
  );
}

/** Non-disclosing rendering of a failed request, with the correlation reference to quote. */
export function ErrorBanner({ error, title = "The request could not be completed", onRetry }: { error: unknown; title?: string; onRetry?: () => void }) {
  const ref = isApiError(error) ? error.correlationId : undefined;
  return (
    <Banner tone={isApiError(error) && error.status === 429 ? "warn" : "danger"} title={title}>
      <span className="err-line">{describeError(error)}</span>
      {onRetry || ref ? <span className="err-actions">
        {onRetry ? <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>Try again</button> : null}
        {ref ? <span className="err-ref">Reference <IdChip value={ref} length={8} label="Error reference" /></span> : null}
      </span> : null}
    </Banner>
  );
}

// ── stats ──────────────────────────────────────────────────────
export interface Stat {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "warn" | "danger" | "ok";
}

export function Stats({ items }: { items: Stat[] }) {
  return (
    <div className="grid-cells stats">
      {items.map((s) => (
        <div className="stat" key={s.label}>
          <span className="label-caps">{s.label}</span>
          <span className={`value${s.tone ? ` ${s.tone}` : ""}`}>{s.value}</span>
          <span className="note">{s.note ?? ""}</span>
        </div>
      ))}
    </div>
  );
}

// ── tabs ───────────────────────────────────────────────────────
export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: T[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist" aria-label="Audit views">
      {tabs.map((t) => (
        <button key={t} id={`tab-${t.replaceAll(' ', '-')}`} aria-controls="view-panel" tabIndex={t === value ? 0 : -1} type="button" role="tab" aria-selected={t === value} className={t === value ? "active" : ""} onClick={() => onChange(t)} onKeyDown={event => {
          const index = tabs.indexOf(t);
          const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
          if (next < 0) return;
          event.preventDefault(); onChange(tabs[next]);
          document.getElementById(`tab-${tabs[next].replaceAll(' ', '-')}`)?.focus();
        }}>
          {t}
        </button>
      ))}
    </div>
  );
}

// ── filters ────────────────────────────────────────────────────
export interface FilterSpec {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options?: string[];
  placeholder?: string;
}

export function FilterBar({ filters, onClear }: { filters: FilterSpec[]; onClear: () => void }) {
  return (
    <div className={`filters${filters.length === 1 ? " single" : ""}`}>
      {filters.map((f) => (
        <div className="field" key={f.id}>
          <label htmlFor={`f-${f.id}`}>{f.label}</label>
          {f.options ? (
            <select className="input" id={`f-${f.id}`} value={f.value} onChange={(e) => f.onChange(e.target.value)}>
              {f.options.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : (
            <input className="input" id={`f-${f.id}`} type="text" placeholder={f.placeholder} value={f.value} onChange={(e) => f.onChange(e.target.value)} />
          )}
        </div>
      ))}
      <button type="button" className="btn btn-secondary" onClick={onClear}>
        Clear
      </button>
    </div>
  );
}

// ── skeleton / empty ───────────────────────────────────────────
export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="skeleton" role="status" aria-busy="true" aria-label="Loading">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} />
      ))}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: { label: string; onClick: () => void } }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{body}</p>
      {action ? (
        <button type="button" className="btn btn-primary" style={{ marginTop: 6 }} onClick={action.onClick}>
          {action.label}
        </button>
      ) : null}
    </div>
  );
}

// ── definition list ────────────────────────────────────────────
export interface DlItem {
  label: string;
  value?: ReactNode;
  mono?: boolean;
  copy?: string;
  badge?: ReactNode;
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const { copy } = useToast();
  return (
    <button type="button" className="btn btn-secondary btn-xs" onClick={() => copy(value)}>
      {label}
    </button>
  );
}

function DlEntries({ items }: { items: DlItem[] }) {
  return (
    <>
      {items.map((d) => (
        <div key={d.label}>
          <dt>{d.label}</dt>
          <dd>
            {d.badge}
            {d.copy && d.mono && d.value === d.copy ? <IdChip value={d.copy} length={d.copy.length > 24 ? 13 : 40} label={d.label} />
              : <>{d.value !== undefined && d.value !== null && d.value !== "" ? <span className={`v${d.mono && (typeof d.value !== "string" || isCodeLike(d.value)) ? " mono" : ""}`}>{d.value}</span> : null}
                {d.copy ? <IdChip value={d.copy} display="Copy" label={d.label} /> : null}</>}
          </dd>
        </div>
      ))}
    </>
  );
}

export function DefinitionList({ items }: { items: DlItem[] }) {
  return (
    <dl className="grid-cells dl">
      <DlEntries items={items} />
    </dl>
  );
}

// ── table ──────────────────────────────────────────────────────
export interface Column {
  label: string;
  align?: "left" | "right";
}

export function Cell({
  children,
  mono,
  muted,
  align,
  sub,
}: {
  children?: ReactNode;
  mono?: boolean;
  muted?: boolean;
  align?: "left" | "right";
  sub?: ReactNode;
}) {
  return (
    <td className={align === "right" ? "right" : undefined}>
      <span className={`${mono && (typeof children !== "string" || isCodeLike(children)) ? "td-mono" : mono ? "td-num" : ""}${muted ? " td-muted" : ""}`.trim() || undefined}>{children}</span>
      {sub ? <div className="sub">{sub}</div> : null}
    </td>
  );
}

export interface RowAction {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  reason?: string;
  danger?: boolean;
}

export function ActionsCell({ actions }: { actions: RowAction[] }) {
  return (
    <td>
      <span className="cell-actions">
        {actions.map((a) => (
          <button
            key={a.label}
            type="button"
            className={`btn btn-xs ${a.danger ? "btn-secondary" : "btn-ghost"}`}
            disabled={a.disabled}
            title={a.reason}
            onClick={a.onClick}
          >
            {a.label}
          </button>
        ))}
      </span>
    </td>
  );
}

export function DataTable({
  columns,
  rows,
  minWidth = 760,
  count,
  title,
  empty,
  footer,
}: {
  columns: (string | Column)[];
  rows: ReactNode[];
  minWidth?: number;
  count?: string;
  title?: string;
  empty?: { title: string; body: string; action?: { label: string; onClick: () => void } };
  /** Extra footer content, e.g. a "Load more" control for paged lists. */
  footer?: ReactNode;
}) {
  return (
    <section className="table-section">
      {title ? <h2>{title}</h2> : null}
      {rows.length ? <p className="table-scroll-hint">Scroll horizontally to see all columns →</p> : null}
      {rows.length === 0 && empty ? <EmptyState {...empty} /> : <div className="table-wrap" tabIndex={0} role="region" aria-label={title ?? "Results table"}>
        <table className="table" style={{ minWidth }}>
          <thead>
            <tr>
              {columns.map((c, i) => {
                const col = typeof c === "string" ? { label: c } : c;
                return (
                  <th scope="col" key={i} className={col.align === "right" ? "right" : undefined}>
                    {col.label || <span className="sr-only">Actions</span>}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>}
      {count || footer ? (
        <div className="table-foot">
          {count ? <span className="count">{count}</span> : null}
          {footer}
        </div>
      ) : null}
    </section>
  );
}

// ── panels ─────────────────────────────────────────────────────
export interface PanelAction {
  label: string;
  onClick: () => void;
  variant?: "primary" | "secondary";
  disabled?: boolean;
  reason?: string;
}

export function Panel({
  title,
  badge,
  note,
  body,
  dl,
  actions,
  children,
}: {
  title: string;
  badge?: ReactNode;
  note?: ReactNode;
  body?: ReactNode;
  dl?: DlItem[];
  actions?: PanelAction[];
  children?: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="p-head">
        <h2>{title}</h2>
        {badge}
        {note ? <span className="p-note">{note}</span> : null}
      </div>
      {body ? <p className="p-body">{body}</p> : null}
      {dl && dl.length ? (
        <dl className="p-dl">
          <DlEntries items={dl} />
        </dl>
      ) : null}
      {children}
      {actions && actions.length ? (
        <div className="p-actions">
          {actions.map((a) => (
            <span className="action" key={a.label}>
              <button
                type="button"
                className={`btn ${a.variant === "primary" ? "btn-primary" : "btn-secondary"}`}
                disabled={a.disabled}
                title={a.reason}
                onClick={a.onClick}
              >
                {/^refresh/i.test(a.label) ? REFRESH_SVG : null}{a.label}
              </button>
              {a.reason ? <span className="reason">{a.reason}</span> : null}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function Snippet({ label, code }: { label: string; code: string }) {
  return (
    <div className="snippet">
      <div className="s-head">
        <span className="s-label">{label}</span>
        <span style={{ marginLeft: "auto" }}>
          <CopyButton value={code} />
        </span>
      </div>
      <pre>{code}</pre>
    </div>
  );
}

export function PanelTable({ columns, rows }: { columns: (string | Column)[]; rows: ReactNode[] }) {
  return (
    <>
    <p className="table-scroll-hint">Scroll horizontally to see all columns →</p>
    <div className="table-wrap" tabIndex={0} role="region" aria-label="Details table">
      <table className="table" style={{ minWidth: 640 }}>
        <thead>
          <tr>
            {columns.map((c, i) => {
              const col = typeof c === "string" ? { label: c } : c;
              return (
                <th scope="col" key={i} className={col.align === "right" ? "right" : undefined}>
                  {col.label}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    </>
  );
}

export function Footnote({ children }: { children: ReactNode }) {
  return <p className="footnote">{children}</p>;
}
