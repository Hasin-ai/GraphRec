/**
 * The loading / empty / failure states §10 requires, once.
 *
 * Fifteen pages each writing `if (isLoading) return <Spinner/>` is fifteen
 * chances to render a bare spinner on a full page, which §10 forbids by name.
 * This renders a skeleton shaped like the thing that is coming.
 *
 * Failures here are *not* thrown to the error boundary, with one exception. A
 * list that fails on a page whose other three panels loaded should degrade to
 * a message in its own region — replacing the whole page with `/error` throws
 * away the three that worked. Loader failures still reach the boundary,
 * because there the page genuinely has nothing.
 *
 * The exception is gates 3 and 4. A 404 means the resource does not exist or
 * is not this tenant's — §13 requires `/404` for both, and a banner reading
 * "That could not be loaded" on an otherwise complete detail page is not that.
 * Those two statuses are rethrown so the boundary renders the right page.
 */

import type { ReactNode } from 'react';
import { Banner, EmptyState, LoadingAnnouncement, Skeleton, TableSkeleton } from '../ui';
import { isApiError } from '../api/errors';

export interface QueryStateProps<T> {
  query: {
    data: T | undefined;
    isPending: boolean;
    error: unknown;
  };
  /** `table` draws rows; `panel` draws blocks. */
  shape?: 'table' | 'panel';
  label: string;
  /** Column count for the table skeleton, so it is the right width. */
  columns?: number;
  empty?: { headline: string; body: string; action?: ReactNode };
  isEmpty?: (data: T) => boolean;
  children: (data: T) => ReactNode;
}

export function QueryState<T>({
  query,
  shape = 'panel',
  label,
  columns,
  empty,
  isEmpty,
  children,
}: QueryStateProps<T>) {
  if (query.isPending) {
    return (
      <>
        <LoadingAnnouncement what={label} />
        {shape === 'table' ? (
          // Wrapped in a table of its own. `TableSkeleton` is a `<tbody>`,
          // because `Table` uses it as one; rendering it bare here put a
          // `<tbody>` directly inside a `<div>`, which no browser parses as
          // written and which a screen reader has no row semantics for.
          <table className="table" aria-hidden="true">
            <TableSkeleton columns={columns ?? 4} />
          </table>
        ) : (
          <Skeleton count={4} />
        )}
      </>
    );
  }

  if (query.error) {
    // Gate 4 (and 3): thrown from render, which the route's `errorElement`
    // catches exactly as it catches a loader's throw. `RouteErrorBoundary`
    // reads `ApiError` directly, so the error is rethrown as it arrived
    // rather than repackaged into a `Response` the boundary would not
    // recognise outside a loader.
    if (isApiError(query.error) && (query.error.status === 404 || query.error.status === 403)) {
      throw query.error;
    }
    const reason = isApiError(query.error)
      ? query.error.body.reason
      : 'That could not be loaded.';
    const reference = isApiError(query.error) ? query.error.reference : null;
    return (
      <Banner kind="danger">
        {reason}
        {reference ? <> Reference: {reference}.</> : null}
      </Banner>
    );
  }

  const data = query.data as T;
  if (empty && isEmpty?.(data)) {
    return <EmptyState headline={empty.headline} body={empty.body} action={empty.action} />;
  }
  return <>{children(data)}</>;
}
