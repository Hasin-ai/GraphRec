import { Link } from 'react-router-dom';
import { Fragment } from 'react';

export interface Crumb {
  label: string;
  /** Absent on the last crumb, which is the page you are on. */
  to?: string;
}

/**
 * §11: the tenant name is the root crumb, because tenant scope lives in the
 * session rather than the path — there is no tenant segment to derive it from
 * and §13 forbids adding one. Public and error routes render no breadcrumb at
 * all, so they simply do not mount this.
 */
export function Breadcrumbs({ crumbs }: { crumbs: readonly Crumb[] }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      {crumbs.map((crumb, index) => (
        <Fragment key={`${crumb.label}-${index}`}>
          {index > 0 ? (
            <span className="crumbs__sep" aria-hidden="true">
              ›
            </span>
          ) : null}
          {crumb.to ? (
            <Link to={crumb.to}>{crumb.label}</Link>
          ) : (
            <span aria-current="page">{crumb.label}</span>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
