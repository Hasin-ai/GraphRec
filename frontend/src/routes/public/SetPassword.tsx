import { useCallback, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Banner, Button, Input } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import type { SetPasswordRequest, UserResponse } from '../../api/hooks/auth';

interface SetPasswordCardProps {
  title: string;
  lede: string;
  /** What the token is called to the reader: a recovery proof, or an invitation. */
  tokenLabel: string;
  action: (body: SetPasswordRequest) => Promise<UserResponse>;
  submitLabel: string;
  /** Shown on `/login`, since both flows end at sign-in. A whole sentence. */
  doneMessage: string;
}

/**
 * The shared body of `/recover/confirm` and `/invite/accept`.
 *
 * §5b says invitation acceptance mirrors recovery confirmation, and they are
 * one component because the security properties are identical: a stranger
 * presents an opaque string and new authentication material, and every refusal
 * — expired, already used, never existed, wrong tenant — comes back as one
 * indistinguishable message.
 *
 * The confirmation field is **not** checked here before sending. The server
 * compares it first, before it looks the token up, precisely so that a typo
 * cannot consume a single-use proof; letting the server answer keeps that
 * ordering the only implementation of the rule rather than one of two.
 */
export function SetPasswordCard({
  title,
  lede,
  tokenLabel,
  action,
  submitLabel,
  doneMessage,
}: SetPasswordCardProps) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // Arrives in the emailed link; typed by hand when the link was mangled.
  const [token, setToken] = useState(() => params.get('token') ?? '');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');

  const onSuccess = useCallback(() => {
    navigate('/login', { replace: true, state: { notice: doneMessage } });
  }, [navigate, doneMessage]);

  const { pending, error, fieldErrors, submit } = useSubmit(action, onSuccess);

  return (
    <div className="card">
      <h1 className="card__title">{title}</h1>
      <p className="card__lede">{lede}</p>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit({ token, password, password_confirmation: confirmation });
        }}
      >
        {error ? <Banner kind="danger">{error.body.reason}</Banner> : null}
        <Input
          label={tokenLabel}
          name="token"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          {...(fieldErrors['token'] ? { error: fieldErrors['token'] } : {})}
          mono
          required
        />
        <Input
          label="New password"
          name="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          hint="At least 12 characters."
          {...(fieldErrors['password'] ? { error: fieldErrors['password'] } : {})}
          autoComplete="new-password"
          minLength={12}
          required
        />
        <Input
          label="Confirm new password"
          name="password_confirmation"
          type="password"
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          {...(fieldErrors['password_confirmation']
            ? { error: fieldErrors['password_confirmation'] }
            : {})}
          autoComplete="new-password"
          required
        />
        <div className="form-actions">
          <Button type="submit" variant="primary" loading={pending} disabled={pending}>
            {submitLabel}
          </Button>
        </div>
      </form>
      <div className="card__foot">
        <Link to="/login">Return to sign in</Link>
      </div>
    </div>
  );
}
