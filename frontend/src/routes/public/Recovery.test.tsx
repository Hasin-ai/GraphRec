import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RecoverConfirmRoute, RecoverRoute } from './Recover';
import { InviteAcceptRoute } from './InviteAccept';
import { RegisterRoute } from './Register';
import { renderRoutes } from '../../test/harness';
import { resetSessionsForTest } from '../../api/session';
import { requestBody } from '../../test/request';

const ACCEPTED = {
  detail: 'If that identifier matches an account, recovery instructions have been sent.',
};

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function routes(element: React.ReactElement, path: string) {
  return [
    { path, element },
    { path: '/login', element: <h1>Sign in</h1> },
  ];
}

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
  vi.stubGlobal('fetch', vi.fn());
});

describe('/recover', () => {
  async function requestFor(email: string) {
    const user = userEvent.setup();
    const view = renderRoutes(routes(<RecoverRoute />, '/recover'), ['/recover']);
    await user.type(screen.getByLabelText(/organisation code/i), 'acme');
    await user.type(screen.getByLabelText(/^email/i), email);
    await user.click(screen.getByRole('button', { name: /send recovery instructions/i }));
    const heading = await screen.findByRole('heading', { name: /check your email/i });
    const html = heading.closest('.card')?.outerHTML ?? '';
    view.unmount();
    return html;
  }

  it('answers a real account and an invented one identically, character for character', async () => {
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(json(202, ACCEPTED))
      .mockResolvedValueOnce(json(202, ACCEPTED));

    // This is the property, and comparing the two renderings to each other —
    // rather than each to a fixed string — is what makes the test hard to
    // weaken by accident. Any branch on whether the account exists shows up
    // here as a diff.
    const real = await requestFor('admin@acme.test');
    const invented = await requestFor('nobody@acme.test');

    expect(invented).toBe(real);
  });

  it("shows the server's sentence rather than one of its own", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(202, ACCEPTED));
    const rendered = await requestFor('admin@acme.test');
    expect(rendered).toContain(ACCEPTED.detail);
  });
});

describe('/recover/confirm', () => {
  it('takes the proof from the link so it is not retyped by hand', () => {
    renderRoutes(routes(<RecoverConfirmRoute />, '/recover/confirm'), [
      '/recover/confirm?token=rec_abc123',
    ]);
    expect(screen.getByLabelText(/recovery proof/i)).toHaveValue('rec_abc123');
  });

  it('sends the confirmation field instead of comparing it here', async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, { tenant_user_id: 'u1' }));

    renderRoutes(routes(<RecoverConfirmRoute />, '/recover/confirm'), [
      '/recover/confirm?token=rec_abc123',
    ]);
    await user.type(screen.getByLabelText(/^new password/i), 'correct-horse-battery');
    await user.type(screen.getByLabelText(/^confirm new password/i), 'mistyped-horse-batter');
    await user.click(screen.getByRole('button', { name: /set password/i }));

    // The server compares the two *before* it looks the proof up, so a typo
    // cannot consume a single-use token. Checking here as well would make that
    // ordering one of two implementations of the rule.
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const [, init] = vi.mocked(globalThis.fetch).mock.calls[0] as unknown as [string, RequestInit];
    expect(requestBody(init.body)).toEqual({
      token: 'rec_abc123',
      password: 'correct-horse-battery',
      password_confirmation: 'mistyped-horse-batter',
    });
  });

  it('shows the refusal without saying which part of the proof was wrong', async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      json(401, {
        error: {
          class: 'auth',
          code: 'recovery_token_invalid',
          reason: 'That recovery proof cannot be used. Request a new one.',
          reference: 'err-2',
          field_errors: [],
          retryable: false,
          retry_after_seconds: null,
        },
      }),
    );

    renderRoutes(routes(<RecoverConfirmRoute />, '/recover/confirm'), ['/recover/confirm']);
    await user.type(screen.getByLabelText(/recovery proof/i), 'rec_wrong');
    await user.type(screen.getByLabelText(/^new password/i), 'correct-horse-battery');
    await user.type(screen.getByLabelText(/^confirm new password/i), 'correct-horse-battery');
    await user.click(screen.getByRole('button', { name: /set password/i }));

    const banner = await screen.findByRole('alert');
    expect(banner.textContent).not.toMatch(/expired|already used|no such|unknown account/i);
  });
});

describe('/invite/accept', () => {
  it('is the same form as recovery confirmation, pointed at the invitation endpoint', async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, { tenant_user_id: 'u1' }));

    renderRoutes(routes(<InviteAcceptRoute />, '/invite/accept'), ['/invite/accept?token=inv_1']);
    await user.type(screen.getByLabelText(/^new password/i), 'correct-horse-battery');
    await user.type(screen.getByLabelText(/^confirm new password/i), 'correct-horse-battery');
    await user.click(screen.getByRole('button', { name: /activate account/i }));

    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    const [url] = vi.mocked(globalThis.fetch).mock.calls[0] as unknown as [string];
    expect(url).toBe('/v1/invitations:accept');
    await screen.findByRole('heading', { name: /sign in/i });
  });
});

describe('/register', () => {
  it('keeps the form filled and attaches the field error where the correction goes', async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      json(409, {
        error: {
          class: 'conflict',
          code: 'tenant_code_taken',
          reason: 'That organisation code is already in use. Choose another.',
          reference: 'err-3',
          field_errors: [{ field: 'tenant_code', reason: 'Already in use.' }],
          retryable: false,
          retry_after_seconds: null,
        },
      }),
    );

    renderRoutes(routes(<RegisterRoute />, '/register'), ['/register']);
    await user.type(screen.getByLabelText(/organisation name/i), 'Acme Ltd');
    await user.type(screen.getByLabelText(/organisation code/i), 'acme');
    await user.type(screen.getByLabelText(/your email/i), 'admin@acme.test');
    await user.type(screen.getByLabelText(/^password/i), 'correct-horse-battery');
    await user.click(screen.getByRole('button', { name: /^register$/i }));

    await screen.findByText('Already in use.');
    // §7: "the form stays filled". Clearing it would make the registrant retype
    // work the server has just told them is nearly right.
    expect(screen.getByLabelText(/organisation name/i)).toHaveValue('Acme Ltd');
    expect(screen.getByLabelText(/organisation code/i)).toHaveValue('acme');
  });

  it('ends at sign-in, because registration issues no session', async () => {
    const user = userEvent.setup();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      json(201, { tenant_id: 't1', tenant_code: 'acme', tenant_name: 'Acme Ltd', status: 'pending' }),
    );

    renderRoutes(routes(<RegisterRoute />, '/register'), ['/register']);
    await user.type(screen.getByLabelText(/organisation name/i), 'Acme Ltd');
    await user.type(screen.getByLabelText(/organisation code/i), 'acme');
    await user.type(screen.getByLabelText(/your email/i), 'admin@acme.test');
    await user.type(screen.getByLabelText(/^password/i), 'correct-horse-battery');
    await user.click(screen.getByRole('button', { name: /^register$/i }));

    await screen.findByRole('heading', { name: /sign in/i });
  });
});
