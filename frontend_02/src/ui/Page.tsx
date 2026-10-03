import { useEffect, type ReactNode } from "react";
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
  icon?: "refresh";
}

const REFRESH_ICON = <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14"><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>;

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {items.map((c, i) => {
        const last = i === items.length - 1;
        const style = c.mono ? { fontFamily: "var(--mono)" } : undefined;
        return (
          <span key={i}>
            {c.to && !last ? (
              <Link to={c.to} style={style}>
                {c.label === "Home" ? "Overview" : c.label}
              </Link>
            ) : (
              <span className={last ? "current" : undefined} aria-current={last ? "page" : undefined} style={style}>
                {c.label === "Home" ? "Overview" : c.label}
              </span>
            )}
            {!last ? <span className="sep">{"›"}</span> : null}
          </span>
        );
      })}
    </nav>
  );
}

/**
 * The page frame every screen shares: optional breadcrumbs, kicker, title with
 * a state badge and actions, a subtitle, and the body stack.
 */
export function Page({
  crumbs,
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
  useEffect(() => { document.title = `${title} · GraphRec`; }, [title]);
  return (
    <>
      {crumbs && crumbs.length ? <Breadcrumbs items={crumbs} /> : null}
      <header className="page-header">
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
                    {a.icon === "refresh" || /^refresh/i.test(a.label) ? REFRESH_ICON : null}{a.label === "Refresh" ? "Refresh data" : a.label}
                  </button>
                  {a.reason ? <span className="reason">{a.reason}</span> : null}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        {subtitle ? <p className="subtitle">{subtitle}</p> : null}
        {updated ? <div className="updated">{updated}</div> : null}
      </header>
      <div className="page-body">{children}</div>
    </>
  );
}
