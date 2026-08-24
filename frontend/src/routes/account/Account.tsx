/**
 * `/account` — the caller's own profile and password.
 *
 * Deliberately thin. What a person may change about themselves is their
 * display name and their password; role, status and email are somebody else's
 * decision, and showing them as read-only text says that more clearly than
 * omitting them would.
 */

import { useState } from 'react';
import { useTenantContext } from '../../layouts/TenantLayout';
import { changeOwnPassword, updateOwnProfile } from '../../api/hooks/operations';
import type { S } from '../../api/schema';
import { readRefreshToken } from '../../api/session';
import { Badge, Banner, Button, DefinitionList, Input } from '../../ui';
import { TENANT_ROLE_LABELS } from '../../lib/enums';
import type { TenantRole } from '../../lib/enums';
import { useSubmit } from '../../lib/useSubmit';

export function AccountRoute() {
  const { me, tenant } = useTenantContext();

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Your account</h1>
        <p className="page__lede">
          You are signed in to {tenant.tenant_name}. An account belongs to one organisation — the
          same address at another organisation is a different account.
        </p>
      </div>

      <div className="two-column">
        <section className="card">
          <h2 className="card__title">Profile</h2>
          <DefinitionList
            items={[
              { term: 'Email', value: me.email },
              { term: 'Role', value: TENANT_ROLE_LABELS[me.role as TenantRole] ?? me.role },
              { term: 'Status', value: <Badge domain="user" value={me.status} /> },
            ]}
          />
          <ProfileForm displayName={me.display_name} />
        </section>

        <section className="card">
          <h2 className="card__title">Password</h2>
          <PasswordForm />
        </section>
      </div>
    </div>
  );
}

function ProfileForm({ displayName }: { displayName: string }) {
  const [value, setValue] = useState(displayName);
  const [saved, setSaved] = useState(false);
  const form = useSubmit<S['MeResponse']>(
    (body: S['UpdateProfileRequest']) => updateOwnProfile(body),
    () => setSaved(true),
  );

  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        setSaved(false);
        form.submit({ display_name: value.trim() });
      }}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      {saved ? <Banner kind="success">Saved. It appears on audit entries from now on.</Banner> : null}
      <Input
        label="Display name"
        value={value}
        required
        error={form.fieldErrors.display_name}
        onChange={(event) => {
          setSaved(false);
          setValue(event.target.value);
        }}
        hint="How you are named to administrators of this organisation."
      />
      <p className="action-row">
        <Button type="submit" disabled={value.trim() === displayName || form.pending}>
          {form.pending ? 'Saving…' : 'Save'}
        </Button>
      </p>
    </form>
  );
}

/**
 * Changing a password ends every other session for the account.
 *
 * The one exception is the session doing the typing, and it earns that by
 * presenting its own refresh token as `keep_session` — the server keeps the
 * session that can prove it is this one, rather than trusting a claim that it
 * is. The alternative, signing the reader out of the page they are on, teaches
 * people not to change their password.
 */
function PasswordForm() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [done, setDone] = useState(false);

  const form = useSubmit<S['MeResponse']>(
    (body: S['ChangeOwnPasswordRequest']) => changeOwnPassword(body),
    () => {
      setDone(true);
      setCurrent('');
      setNext('');
      setConfirmation('');
    },
  );

  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        setDone(false);
        form.submit({
          current_password: current,
          password: next,
          password_confirmation: confirmation,
          keep_session: readRefreshToken('tenant'),
        });
      }}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      {done ? (
        <Banner kind="success">
          Password changed. Every other session for this account has been signed out; this one is
          still yours.
        </Banner>
      ) : null}
      <Input
        label="Current password"
        type="password"
        required
        autoComplete="current-password"
        value={current}
        error={form.fieldErrors.current_password}
        onChange={(event) => setCurrent(event.target.value)}
      />
      <Input
        label="New password"
        type="password"
        required
        autoComplete="new-password"
        value={next}
        error={form.fieldErrors.password}
        onChange={(event) => setNext(event.target.value)}
        hint="At least 12 characters."
      />
      <Input
        label="Repeat new password"
        type="password"
        required
        autoComplete="new-password"
        value={confirmation}
        error={form.fieldErrors.password_confirmation}
        onChange={(event) => setConfirmation(event.target.value)}
      />
      <p className="action-row">
        <Button type="submit" disabled={form.pending || !current || !next}>
          {form.pending ? 'Changing…' : 'Change password'}
        </Button>
      </p>
    </form>
  );
}
