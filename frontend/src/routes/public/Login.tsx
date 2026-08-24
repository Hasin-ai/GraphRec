import { useCallback, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Banner, Button, Input } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { signIn } from '../../api/hooks/auth';

/**
 * `/login`.
 *
 * Every rejection here reads the same. The server answers `invalid_credentials`
 * for a wrong password, an unknown address, an unknown tenant code, a locked
 * account and a disabled one, and this page renders that sentence unchanged —
 * so the form cannot be used to find out which accounts exist. Rate limiting is
 * the server's, and its refusal arrives in the same banner.
 */
export function LoginRoute() {
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const [tenantCode, setTenantCode] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  // Where the reader was going before gate 1 stopped them. Same-origin paths
  // only: an absolute URL here would make this an open redirect.
  const next = params.get('next');
  const destination = next && next.startsWith('/') && !next.startsWith('//') ? next : '/home';

  // Set by whichever page sent them here — registration, recovery, invitation.
  const notice = (location.state as { notice?: string } | null)?.notice;

  const onSuccess = useCallback(() => {
    void navigate(destination, { replace: true });
  }, [navigate, destination]);

  const { pending, error, submit } = useSubmit(signIn, onSuccess);

  return (
    <div className="card">
      <h1 className="card__title">Sign in</h1>
      <p className="card__lede">Your organisation's code, and your own credentials.</p>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit({ tenant_code: tenantCode, email, password });
        }}
      >
        {notice ? <Banner kind="success">{notice}</Banner> : null}
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
        <Input
          label="Password"
          name="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
        />
        <div className="form-actions">
          <Button type="submit" variant="primary" loading={pending} disabled={pending}>
            Sign in
          </Button>
        </div>
      </form>
      <div className="card__foot">
        <Link to="/recover">Forgotten your password?</Link>
        <Link to="/register">Register an organisation</Link>
      </div>
    </div>
  );
}
