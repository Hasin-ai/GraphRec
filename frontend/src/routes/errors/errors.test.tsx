import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { redirect } from 'react-router-dom';
import { FailurePage, ForbiddenPage, NotFoundPage } from './pages';
import { RouteErrorBoundary } from './RouteErrorBoundary';
import { renderPage, renderRoutes } from '../../test/harness';
import { ApiError } from '../../api/errors';

function apiError(status: number, code: string) {
  return new ApiError(status, {
    class: 'not_found',
    code,
    reason: 'Refused.',
    reference: 'err-9999-zzzzz',
    field_errors: [],
    retryable: false,
    retry_after_seconds: null,
  });
}

function boundaryFor(thrown: unknown) {
  return renderRoutes(
    [
      {
        path: '/thing',
        loader: () => {
          throw thrown;
        },
        element: <h1>Never rendered</h1>,
        errorElement: <RouteErrorBoundary />,
      },
      { path: '/login', element: <h1>Sign in</h1> },
    ],
    ['/thing'],
  );
}

describe('/403', () => {
  it('offers no way to try again', () => {
    renderPage('/403', <ForbiddenPage />);
    // §7: terminal by design. The activity diagram routes permission errors
    // straight to exit, and a retry control invites hunting for another door.
    expect(screen.queryByRole('button')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('/404', () => {
  it('names no resource, so missing and foreign stay indistinguishable', () => {
    renderPage('/404', <NotFoundPage />);
    const text = document.body.textContent ?? '';
    for (const noun of ['product', 'model', 'training', 'user', 'credential', 'tenant']) {
      expect(text.toLowerCase()).not.toContain(noun);
    }
  });
});

describe('/error', () => {
  it('carries the reference and nothing else identifying', () => {
    renderPage('/error', <FailurePage reference="err-4242-abcde" />);
    expect(screen.getByText(/err-4242-abcde/)).toBeVisible();
  });

  it('omits the reference line entirely when there is none to quote', () => {
    renderPage('/error', <FailurePage reference={null} />);
    expect(screen.queryByText(/reference:/i)).toBeNull();
  });
});

describe('the error boundary', () => {
  it('renders 403 for a permission refusal thrown as a Response', async () => {
    boundaryFor(new Response('Forbidden', { status: 403 }));
    expect(await screen.findByText(/do not have access/i)).toBeVisible();
  });

  it('renders 404 for a foreign resource, never 403', async () => {
    // The API answers 404 for "not yours" as well as "not there"; a boundary
    // that upgraded it to 403 would confirm the resource exists.
    boundaryFor(apiError(404, 'not_found'));
    expect(await screen.findByText(/not found/i)).toBeVisible();
    expect(screen.queryByText(/do not have access/i)).toBeNull();
  });

  it('sends a genuinely expired session to sign in rather than to an error page', async () => {
    boundaryFor(apiError(401, 'invalid_credentials'));
    expect(await screen.findByRole('heading', { name: /sign in/i })).toBeVisible();
  });

  it('shows the reference for anything it does not recognise', async () => {
    boundaryFor(apiError(500, 'internal_error'));
    expect(await screen.findByText(/err-9999-zzzzz/)).toBeVisible();
  });

  it('lets a redirect through untouched', async () => {
    // A guard signals gate 2 by throwing a redirect. If the boundary caught
    // that as an error, every gate-2 redirect would render /error instead.
    renderRoutes(
      [
        {
          path: '/thing',
          loader: () => {
            throw redirect('/account/tenant-status');
          },
          element: <h1>Never rendered</h1>,
          errorElement: <RouteErrorBoundary />,
        },
        { path: '/account/tenant-status', element: <h1>Status</h1> },
      ],
      ['/thing'],
    );
    expect(await screen.findByRole('heading', { name: 'Status' })).toBeVisible();
  });
});
