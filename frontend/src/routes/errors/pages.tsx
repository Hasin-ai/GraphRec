/**
 * `/403`, `/404` and `/error`.
 *
 * All three are addressable routes *and* the three things the error boundary
 * renders, which is why they live in one file: the boundary must not drift
 * from the page. Each is deliberately unhelpful in a specific way:
 *
 * * **403** is terminal. §7 is explicit — "offer no retry"; the activity
 *   diagram routes permission errors straight to exit. A retry button on a
 *   permission failure invites the reader to hunt for the door that opens.
 * * **404** never names the resource. Missing and foreign are the same answer
 *   (§13), because a 404 that says "product" confirms a product was asked for.
 * * **`/error`** carries the reference and nothing else. No stack, no request
 *   body, no identifiers — that is what the reference is for.
 */

import { Link } from 'react-router-dom';
import { Button } from '../../ui';

interface ErrorPageProps {
  /** Present only on `/error`. Quoting it is the whole support workflow. */
  reference?: string | null;
}

function Frame({
  code,
  title,
  children,
}: {
  code: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="page">
      <div className="errorpage">
        <p className="errorpage__code">{code}</p>
        <h1 className="page__title">{title}</h1>
        {children}
      </div>
    </div>
  );
}

export function ForbiddenPage() {
  return (
    <Frame code="403" title="You do not have access to this">
      <p className="page__lede">
        Your role does not permit this area. Nothing was changed. If you believe this is wrong, ask
        a Tenant Administrator — they control roles for your organisation.
      </p>
    </Frame>
  );
}

export function NotFoundPage() {
  return (
    <Frame code="404" title="Not found">
      <p className="page__lede">
        This address does not resolve to anything you can open. Check the link, or start again from
        the navigation.
      </p>
    </Frame>
  );
}

export function FailurePage({ reference }: ErrorPageProps) {
  return (
    <Frame code="Error" title="Something went wrong">
      <p className="page__lede">
        The request could not be completed. Nothing was partially applied that you need to undo.
        Try again, and quote the reference below if it keeps happening.
      </p>
      {reference ? (
        <p className="errorpage__reference">
          Reference: <strong>{reference}</strong>
        </p>
      ) : null}
      <p style={{ marginTop: 'var(--space-4)' }}>
        <Button variant="secondary" onClick={() => window.location.reload()}>
          Try again
        </Button>
      </p>
    </Frame>
  );
}

/** Shared foot for the standalone (unauthenticated) variants of the above. */
export function BackToSignIn() {
  return (
    <p className="page__lede">
      <Link to="/login">Return to sign in</Link>
    </p>
  );
}
