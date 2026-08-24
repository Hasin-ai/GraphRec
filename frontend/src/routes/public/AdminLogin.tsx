import { useCallback, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Banner, Button, Input } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { platformSignIn } from '../../api/hooks/auth';

/**
 * `/admin/login`. A **separate authentication realm** (§5b).
 *
 * There is no organisation code here, and that absence is the design: a
 * platform operator is not a member of any tenant and resolves no tenant scope,
 * so there is nothing for a code to select. A tenant user's credentials do not
 * work on this form and a platform operator's do not work on `/login`; the two
 * token types are issued and verified separately, and presenting one where the
 * other is expected is refused as a wrong-realm token.
 *
 * The platform realm also issues no refresh route — an operator's session ends
 * and they come back here.
 */
export function AdminLoginRoute() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const onSuccess = useCallback(() => {
    void navigate('/admin', { replace: true });
  }, [navigate]);

  const { pending, error, submit } = useSubmit(platformSignIn, onSuccess);

  return (
    <div className="card">
      <h1 className="card__title">Platform sign in</h1>
      <p className="card__lede">For platform operators. Tenant users sign in at the main form.</p>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit({ email, password });
        }}
      >
        {error ? <Banner kind="danger">{error.body.reason}</Banner> : null}
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
        <Link to="/login">Tenant sign in</Link>
      </div>
    </div>
  );
}
