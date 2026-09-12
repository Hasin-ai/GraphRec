import type { CSSProperties, ReactNode } from "react";
import { Link } from "react-router-dom";
import { describeError, isApiError } from "../api/client";
import { useToast } from "../hooks/useToast";
import { toneFor, type Tone } from "../lib/status";

const TONE_STYLE: Record<Tone, CSSProperties> = {
  ok: { background: "var(--ok-bg)", color: "var(--ok)" },
  warn: { background: "var(--warn-bg)", color: "var(--warn)" },
  danger: { background: "var(--danger-bg)", color: "var(--danger)" },
  info: { background: "var(--info-bg)", color: "var(--info)" },
  neu: { background: "var(--neu-bg)", color: "var(--neu)" },
};

// ── tags ───────────────────────────────────────────────────────
export function Tag({ tone = "neu", mono, children }: { tone?: Tone; mono?: boolean; children: ReactNode }) {
  return (
    <span className={`tag${mono ? " mono" : ""}`} style={TONE_STYLE[tone]}>
      {children}
    </span>
  );
}

/** A state badge: the value in mono with its fixed semantic colour. */
export function Badge({ group, value }: { group: string; value: string }) {
  return (
    <Tag tone={toneFor(group, value)} mono>
      {value}
    </Tag>
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
export function ErrorBanner({ error, title = "The request could not be completed" }: { error: unknown; title?: string }) {
  const ref = isApiError(error) ? error.correlationId : undefined;
  return (
    <Banner tone={isApiError(error) && error.status === 429 ? "warn" : "danger"} title={title}>
      {describeError(error)}
      {ref ? (
        <>
          {" "}
          <span className="mono" style={{ fontSize: 12 }}>
            ref {ref}
          </span>
        </>
      ) : null}
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

// ── stage rail ─────────────────────────────────────────────────
export function StageRail({
  title,
  stages,
  at,
  failed,
  note,
}: {
  title: string;
  stages: readonly string[];
  at: number;
  failed?: boolean;
  note?: ReactNode;
}) {
  return (
    <section className="rail">
      <h2>{title}</h2>
      <div className="stages" style={{ gridTemplateColumns: `repeat(${stages.length}, 1fr)` }}>
        {stages.map((label, i) => {
          const cur = i === at;
          const cls = failed && cur ? "fail" : cur ? "cur" : i < at ? "done" : "";
          return (
            <div className={`stage${cur ? " cur" : ""}`} key={label}>
              <div className={`bar ${cls}`} />
              <span>{label}</span>
            </div>
          );
        })}
      </div>
      {note ? <div className="note">{note}</div> : null}
    </section>
  );
}

// ── tabs ───────────────────────────────────────────────────────
export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: T[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t} type="button" role="tab" aria-selected={t === value} className={t === value ? "active" : ""} onClick={() => onChange(t)}>
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
    <div className="filters">
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

// ── cards / checklist ──────────────────────────────────────────
export interface CardSpec {
  route: string;
  title: string;
  body: string;
}

export function Cards({ items }: { items: CardSpec[] }) {
  return (
    <div className="grid-cells cards">
      {items.map((c) => (
        <Link className="card-link" to={c.route} key={c.route}>
          <span className="route">{c.route}</span>
          <span className="title">{c.title}</span>
          <span className="body">{c.body}</span>
        </Link>
      ))}
    </div>
  );
}

export interface ChecklistStep {
  label: string;
  route: string;
  done: boolean;
  note: string;
}

export function Checklist({ title, steps, onDismiss }: { title: string; steps: ChecklistStep[]; onDismiss: () => void }) {
  const done = steps.filter((s) => s.done).length;
  return (
    <section className="checklist">
      <div className="head">
        <h2>{title}</h2>
        <span className="progress">
          {done} of {steps.length} complete
        </span>
        <button type="button" className="btn btn-secondary btn-sm" style={{ marginLeft: "auto" }} onClick={onDismiss}>
          Dismiss
        </button>
      </div>
      <ol>
        {steps.map((s) => (
          <li key={s.route + s.label}>
            <span className={`mark${s.done ? " done" : ""}`}>{s.done ? "✓" : "—"}</span>
            <Link to={s.route} className={s.done ? "done" : ""}>
              {s.label}
            </Link>
            <Tag tone={s.done ? "ok" : "info"}>{s.done ? "done" : "to do"}</Tag>
            <span className="note">{s.note}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

// ── skeleton / empty ───────────────────────────────────────────
export function Skeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="skeleton" aria-busy="true" aria-label="Loading">
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
            {d.value !== undefined && d.value !== null && d.value !== "" ? <span className={`v${d.mono ? " mono" : ""}`}>{d.value}</span> : null}
            {d.copy ? <CopyButton value={d.copy} /> : null}
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
      <span className={`${mono ? "td-mono" : ""}${muted ? " td-muted" : ""}`.trim() || undefined}>{children}</span>
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
}: {
  columns: (string | Column)[];
  rows: ReactNode[];
  minWidth?: number;
  count?: string;
  title?: string;
  empty?: { title: string; body: string; action?: { label: string; onClick: () => void } };
}) {
  if (rows.length === 0 && empty) return <EmptyState {...empty} />;
  return (
    <section className="table-section">
      {title ? <h2>{title}</h2> : null}
      <div className="table-wrap">
        <table className="table" style={{ minWidth }}>
          <thead>
            <tr>
              {columns.map((c, i) => {
                const col = typeof c === "string" ? { label: c } : c;
                return (
                  <th key={i} className={col.align === "right" ? "right" : undefined}>
                    {col.label}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
      {count ? (
        <div className="table-foot">
          <span className="count">{count}</span>
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
                {a.label}
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
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {columns.map((c, i) => {
              const col = typeof c === "string" ? { label: c } : c;
              return (
                <th key={i} className={col.align === "right" ? "right" : undefined}>
                  {col.label}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  );
}

export function Footnote({ children }: { children: ReactNode }) {
  return <p className="footnote">{children}</p>;
}
