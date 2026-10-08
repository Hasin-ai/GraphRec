import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "./icons";
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
            {!last ? <Icon name="chevron-right" size={13} className="sep" /> : null}
          </span>
        );
      })}
    </nav>
  );
}

function useLoadedStamp(loading: boolean | undefined): number | null {
  const [stamp, setStamp] = useState<number | null>(loading === undefined ? null : loading ? null : Date.now());
  useEffect(() => { if (loading === false) setStamp(Date.now()); }, [loading]);
  return stamp;
}
const timeFmt = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" });

/**
 * PageHeader + body. Breadcrumbs only render for nested pages (detail / create);
 * top-level pages rely on the sidebar for location. A refresh action shows a
 * spinner while loading and the time of the last successful load.
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
  const nested = crumbs && crumbs.length > 2 ? crumbs.slice(1) : null;
  const refresh = actions?.find(a => a.icon === "refresh" || /^refresh/i.test(a.label));
  const stamp = useLoadedStamp(refresh ? !!refresh.disabled : undefined);
  return (
    <>
      <header className="page-header">
        {nested ? <Breadcrumbs items={nested} /> : null}
        <div className="title-row">
          <div className="title-block">
            <div className="title-line"><h1>{title}</h1>{badge}</div>
            {subtitle ? <p className="subtitle">{subtitle}</p> : null}
          </div>
          {actions && actions.length ? (
            <div className="actions">
              {refresh ? <span className="updated-stamp" aria-live="polite">{refresh.disabled ? "Refreshing…" : updated ?? (stamp ? `Updated ${timeFmt.format(stamp)}` : null)}</span> : null}
              {actions.map((a) => {
                const isRefresh = a === refresh;
                return <span className="action" key={a.label}>
                  <button
                    type="button"
                    className={`btn ${a.variant === "primary" ? "btn-primary" : a.variant === "danger" ? "btn-danger" : "btn-secondary"}`}
                    disabled={a.disabled}
                    title={a.reason}
                    aria-busy={isRefresh && a.disabled ? true : undefined}
                    onClick={a.onClick}
                  >
                    {isRefresh ? <Icon name="refresh-cw" size={15} className={a.disabled ? "spin" : undefined} /> : /^\+\s*/.test(a.label) ? <Icon name="plus" size={15} /> : null}
                    {a.label === "Refresh" ? "Refresh" : a.label.replace(/^\+\s*/, "")}
                  </button>
                  {a.reason && !isRefresh ? <span className="reason">{a.reason}</span> : null}
                </span>;
              })}
            </div>
          ) : updated ? <div className="actions"><span className="updated-stamp">{updated}</span></div> : null}
        </div>
      </header>
      <div className="page-body">{children}</div>
    </>
  );
}
