import { useCallback, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Banner, Button, Input } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { registerTenant } from '../../api/hooks/auth';
import type { TenantResponse } from '../../api/hooks/auth';

/**
 * `/register`. Creates the organisation *and* its first administrator; the
 * registrant becomes that administrator.
 *
 * Unlike `/login`, this form is allowed to be specific: a taken organisation
 * code is a `conflict` and saying so is the only way the registrant can pick
 * another one. That discloses that a code is taken, which is unavoidable for
 * an identifier the registrant has to choose and which appears in their own
 * sign-in form afterwards.
 *
 * Registration returns the tenant, not a session — so this ends at `/login`.
 * A newly registered tenant is `pending` until the platform activates it, and
 * signing in will land on `/account/tenant-status` until then. That is gate 2
 * working, not a failure, and the banner below says so in advance.
 */
export function RegisterRoute() {
  const navigate = useNavigate();
  const [tenantName, setTenantName] = useState('');
  const [tenantCode, setTenantCode] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const onSuccess = useCallback(
    (tenant: TenantResponse) => {
      void navigate('/login', {
        replace: true,
        state: { notice: `${tenant.tenant_name} is registered. Sign in to continue.` },
      });
    },
    [navigate],
  );

  const { pending, error, fieldErrors, submit } = useSubmit(registerTenant, onSuccess);

  return (
    <div className="card card--wide">
      <h1 className="card__title">Register an organisation</h1>
      <p className="card__lede">
        You will become its first Tenant Administrator. A Platform Administrator activates the
        organisation before it can be used.
      </p>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit({
            tenant_name: tenantName,
            tenant_code: tenantCode,
            email,
            password,
          });
        }}
      >
        {error ? <Banner kind="danger">{error.body.reason}</Banner> : null}
        <Input
          label="Organisation name"
          name="tenant_name"
          value={tenantName}
          onChange={(event) => setTenantName(event.target.value)}
          {...(fieldErrors['tenant_name'] ? { error: fieldErrors['tenant_name'] } : {})}
          autoComplete="organization"
          maxLength={200}
          required
        />
        <Input
          label="Organisation code"
          name="tenant_code"
          value={tenantCode}
          onChange={(event) => setTenantCode(event.target.value)}
          hint="Letters, digits and hyphens. You will type this every time you sign in."
          {...(fieldErrors['tenant_code'] ? { error: fieldErrors['tenant_code'] } : {})}
          pattern="[A-Za-z0-9][A-Za-z0-9\-]*"
          minLength={2}
          maxLength={32}
          mono
          required
        />
        <Input
          label="Your email"
          name="email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          {...(fieldErrors['email'] ? { error: fieldErrors['email'] } : {})}
          autoComplete="username"
          required
        />
        <Input
          label="Password"
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
        <div className="form-actions">
          <Button type="submit" variant="primary" loading={pending} disabled={pending}>
            Register
          </Button>
        </div>
      </form>
      <div className="card__foot">
        <Link to="/login">Already registered? Sign in</Link>
      </div>
    </div>
  );
}
