import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Banner, Button, Input } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { requestRecovery } from '../../api/hooks/auth';
import { SetPasswordCard } from './SetPassword';
import { confirmRecovery } from '../../api/hooks/auth';

/**
 * `/recover`, step 1.
 *
 * The success message is the server's `detail`, which says the same thing
 * whether or not the account exists — and this page shows it on **every**
 * success, including when nothing was sent. That is the whole point: a page
 * that only confirmed for real accounts would be an account enumerator with
 * extra steps.
 *
 * The only visible asymmetry left is timing, which the server does not equalise
 * either; that is answered by rate limiting at the edge rather than by this
 * form.
 */
export function RecoverRoute() {
  const [tenantCode, setTenantCode] = useState('');
  const [email, setEmail] = useState('');
  const { pending, error, data, submit } = useSubmit(requestRecovery);

  if (data) {
    return (
      <div className="card">
        <h1 className="card__title">Check your email</h1>
        <Banner kind="info">{data.detail}</Banner>
        <p className="card__lede" style={{ marginTop: 'var(--space-4)' }}>
          The message contains a recovery proof. It is usable once, and expires within the hour.
        </p>
        <div className="card__foot">
          <Link to="/recover/confirm">I have a recovery proof</Link>
          <Link to="/login">Return to sign in</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <h1 className="card__title">Recover access</h1>
      <p className="card__lede">
        Tell us which organisation and which address. If they match an account, we will send a
        recovery proof.
      </p>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit({ tenant_code: tenantCode, email });
        }}
      >
        {error ? <Banner kind="danger">{error.body.reason}</Banner> : null}
        <Input
          label="Organisation code"
          name="tenant_code"
          value={tenantCode}
          onChange={(event) => setTenantCode(event.target.value)}
          autoComplete="organization"
          mono
          required
        />
        <Input
          label="Email"
          name="email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="username"
          required
        />
        <div className="form-actions">
          <Button type="submit" variant="primary" loading={pending} disabled={pending}>
            Send recovery instructions
          </Button>
        </div>
      </form>
      <div className="card__foot">
        <Link to="/login">Return to sign in</Link>
      </div>
    </div>
  );
}

/** `/recover/confirm`, step 2. */
export function RecoverConfirmRoute() {
  return (
    <SetPasswordCard
      title="Set a new password"
      lede="Paste the recovery proof from your email, then choose a new password. Every other session on this account is signed out."
      tokenLabel="Recovery proof"
      action={confirmRecovery}
      submitLabel="Set password"
      doneMessage="Your password has been changed. Sign in with it."
    />
  );
}
