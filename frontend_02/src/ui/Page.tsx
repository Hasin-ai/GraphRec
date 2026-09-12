import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export interface Crumb {
  label: string;
  to?: string;
  mono?: boolean;
}

export interface HeaderAction {
  label: string;
  onClick: () => void;
  variant?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  reason?: string;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <div className="crumbs" aria-label="Breadcrumb">
      {items.map((c, i) => {
        const last = i === items.length - 1;
        const style = c.mono ? { fontFamily: "var(--mono)" } : undefined;
        return (
          <span key={i}>
            {c.to && !last ? (
              <Link to={c.to} style={style}>
                {c.label}
              </Link>
            ) : (
              <span className={last ? "current" : undefined} style={style}>
                {c.label}
              </span>
            )}
            {!last ? <span className="sep">{"›"}</span> : null}
          </span>
        );
      })}
    </div>
  );
}

/**
 * The page frame every screen shares: optional breadcrumbs, kicker, title with
 * a state badge and actions, a subtitle, and the body stack.
 */
export function Page({
  crumbs,
  kicker,
  title,
  badge,
  actions,
  subtitle,
  updated,
  children,
}: {
  crumbs?: Crumb[];
  kicker?: string;
  title: string;
  badge?: ReactNode;
  actions?: HeaderAction[];
  subtitle?: ReactNode;
  updated?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <>
      {crumbs && crumbs.length ? <Breadcrumbs items={crumbs} /> : null}
      <header className="page-header">
        {kicker ? <div className="kicker">{kicker}</div> : null}
        <div className="title-row">
          <h1>{title}</h1>
          {badge}
          {actions && actions.length ? (
            <div className="actions">
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
        </div>
        {subtitle ? <p className="subtitle">{subtitle}</p> : null}
        {updated ? <div className="updated pulse">{updated}</div> : null}
      </header>
      <div className="page-body">{children}</div>
    </>
  );
}
