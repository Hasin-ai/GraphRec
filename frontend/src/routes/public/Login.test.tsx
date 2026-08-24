import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoginRoute } from './Login';
import { renderRoutes } from '../../test/harness';
import { hasSession, resetSessionsForTest } from '../../api/session';

const REFUSAL = {
  error: {
    class: 'auth',
    code: 'invalid_credentials',
    reason: 'That combination was not accepted. Check the details and try again.',
    reference: 'err-0001-aaaaa',
    field_errors: [],
    retryable: false,
    retry_after_seconds: null,
  },
};

const SESSION = {
  access_token: 'access-1',
  expires_at: '2026-01-01T00:15:00Z',
  refresh_token: 'refresh-1',
  refresh_expires_at: '2026-01-08T00:00:00Z',
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function routes() {
  return [
    { path: '/login', element: <LoginRoute /> },
    { path: '/home', element: <h1>Home</h1> },
    { path: '/training/:jobId', element: <h1>A training run</h1> },
  ];
}

async function signInAs(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/organisation code/i), 'acme');
  await user.type(screen.getByLabelText(/^email/i), 'admin@acme.test');
  await user.type(screen.getByLabelText(/^password/i), 'correct-horse-battery');
  await user.click(screen.getByRole('button', { name: /sign in/i }));
}

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
  vi.stubGlobal('fetch', vi.fn());
});

describe('/login', () => {
  it('stores a session and goes to /home', async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, SESSION));

    renderRoutes(routes(), ['/login']);
    await signInAs(user);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Home' })).toBeVisible());
    expect(hasSession('tenant')).toBe(true);
  });

  it('returns the reader to where gate 1 stopped them', async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, SESSION));

    renderRoutes(routes(), [`/login?next=${encodeURIComponent('/training/abc')}`]);
    await signInAs(user);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'A training run' })).toBeVisible(),
    );
  });

  it('ignores a `next` pointing off-site', async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, SESSION));

    // An open redirect on a sign-in form hands an attacker a credible way to
    // land a freshly authenticated user on a page they control.
    renderRoutes(routes(), [`/login?next=${encodeURIComponent('//evil.test/steal')}`]);
    await signInAs(user);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Home' })).toBeVisible());
  });

  it("shows the server's sentence, and volunteers nothing about the account", async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(401, REFUSAL));

    renderRoutes(routes(), ['/login']);
    await signInAs(user);

    const banner = await screen.findByRole('alert');
    expect(banner).toHaveTextContent(REFUSAL.error.reason);
    // Nothing that would distinguish "no such account" from "wrong password".
    expect(banner.textContent).not.toMatch(/no such|unknown|does not exist|not found|locked/i);
    expect(hasSession('tenant')).toBe(false);
  });

  it('keeps what was typed, so a rejected attempt is corrected rather than retyped', async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(401, REFUSAL));

    renderRoutes(routes(), ['/login']);
    await signInAs(user);
    await screen.findByRole('alert');

    expect(screen.getByLabelText(/organisation code/i)).toHaveValue('acme');
    expect(screen.getByLabelText(/^email/i)).toHaveValue('admin@acme.test');
  });
});
