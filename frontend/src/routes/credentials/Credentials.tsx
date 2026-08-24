/**
 * `/credentials` — the list, and the three dialogs that change it.
 *
 * The hard constraint (§13, §10.6) lives here: **the one-time secret is a modal
 * and never a route.** A route holding a secret is a URL holding a secret, and
 * a URL is in history, in the address bar, in a screenshot, and in whatever
 * synchronises browser tabs. It is also re-openable, which is the one thing a
 * value shown exactly once must not be.
 *
 * So the secret exists in exactly one place: a `useState` in this component,
 * set by the mutation's response and cleared when the dialog closes. It is not
 * put in the query cache, because the cache is keyed, shared and survives
 * navigation — three properties that are virtues for a product list and
 * defects for a secret.
 *
 * Everything else on the page is the server's: `state` is server-derived
 * (§10.9's sixth console-only field — server time decides what has expired,
 * not the reader's clock), and `can_rotate` / `can_revoke` / `blocked_reason`
 * are gate 5 arriving as data.
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  createCredential,
  credentialsQuery,
  revokeCredential,
  rotateCredential,
  scopesQuery,
  useCredentialMutation,
} from '../../api/hooks/operations';
import type { Credential, IssuedCredential } from '../../api/hooks/operations';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { GatedAction } from '../../components/gate5';
import { Badge, Banner, Button, CopyField, Dialog, Input, Select, Table } from '../../ui';
import type { Column } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';
import { formatDate, formatDateTime } from '../../lib/format';

type Pending =
  | { kind: 'create' }
  | { kind: 'rotate'; credential: Credential }
  | { kind: 'revoke'; credential: Credential }
  | null;

export function CredentialsRoute() {
  const credentials = useQuery(credentialsQuery());
  const [pending, setPending] = useState<Pending>(null);
  const [issued, setIssued] = useState<IssuedCredential | null>(null);

  const columns: readonly Column<Credential>[] = [
    { key: 'name', header: 'Name', cell: (row) => row.name },
    {
      key: 'prefix',
      header: 'Prefix',
      cell: (row) => <code>{row.visible_prefix}</code>,
    },
    {
      key: 'scopes',
      header: 'Authorizes',
      cell: (row) => (
        <ul className="stack--tight" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {row.scopes.map((scope) => (
            <li key={scope}>{scope}</li>
          ))}
        </ul>
      ),
    },
    {
      key: 'state',
      header: 'State',
      cell: (row) => <Badge domain="credential" value={row.state} />,
    },
    { key: 'expires', header: 'Expires', cell: (row) => formatDate(row.expires_at) },
    { key: 'revoked', header: 'Revoked', cell: (row) => formatDateTime(row.revoked_at) },
    { key: 'created', header: 'Created', cell: (row) => formatDate(row.created_at) },
    { key: 'used', header: 'Last used', cell: (row) => formatDateTime(row.last_used_at) },
    {
      key: 'actions',
      header: 'Actions',
      cell: (row) => (
        <div className="action-row">
          <GatedAction
            label="Rotate"
            allowed={row.can_rotate}
            reason={row.blocked_reason}
            onClick={() => setPending({ kind: 'rotate', credential: row })}
          />
          <GatedAction
            label="Revoke"
            allowed={row.can_revoke}
            reason={row.blocked_reason}
            variant="danger"
            onClick={() => setPending({ kind: 'revoke', credential: row })}
          />
        </div>
      ),
    },
  ];

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Credentials</h1>
        <p className="page__lede">
          What your integration authenticates with. The secret is shown once, at creation or
          rotation, and is not retained by this system — if it is lost, rotate to obtain a new one.
        </p>
      </div>

      <p className="action-row">
        <Button onClick={() => setPending({ kind: 'create' })}>Create credential</Button>
      </p>

      <QueryState
        query={credentials}
        shape="table"
        columns={columns.length}
        label="your credentials"
        isEmpty={(data) => data.credentials.length === 0}
        empty={{
          headline: 'No credentials yet',
          body: 'Nothing can call the API until one exists. Create one, scoped to the operations your integration actually performs.',
        }}
      >
        {(data) => (
          <>
            <p className="checklist__progress">
              {data.credentials.length} of {data.total}
            </p>
            <Table
              caption="Credentials in this tenant"
              columns={columns}
              rows={data.credentials}
              rowKey={(row) => row.key_id}
            />
          </>
        )}
      </QueryState>

      {pending?.kind === 'create' ? (
        <IssueDialog
          title="Create credential"
          onClose={() => setPending(null)}
          onIssued={(result) => {
            setPending(null);
            setIssued(result);
          }}
          build={(picked) => ({
            name: picked.name,
            scopes: picked.scopes,
            expires_in_days: picked.days,
          })}
          action={createCredential}
        />
      ) : null}

      {pending?.kind === 'rotate' ? (
        <IssueDialog
          title={`Rotate ${pending.credential.name}`}
          lede="The existing secret keeps working for a short grace period, so a running integration is not cut off mid-deploy."
          existing={pending.credential}
          onClose={() => setPending(null)}
          onIssued={(result) => {
            setPending(null);
            setIssued(result);
          }}
          build={(picked) => ({
            scopes: picked.scopes,
            // An hour. Long enough for a rolling deploy to pick the new secret
            // up, short enough that a compromised old one is not useful.
            grace_seconds: 3600,
            reason: 'Rotated from the console.',
          })}
          action={(body) => rotateCredential(pending.credential.key_id, body)}
        />
      ) : null}

      {pending?.kind === 'revoke' ? (
        <RevokeDialog
          credential={pending.credential}
          onClose={() => setPending(null)}
          onDone={() => setPending(null)}
        />
      ) : null}

      {issued ? <SecretDialog issued={issued} onClose={() => setIssued(null)} /> : null}
    </div>
  );
}

/**
 * The one-time secret. Shown once, not re-openable, gone when this closes.
 *
 * `dismissible={false}` is deliberate: closing on `Escape` or a backdrop click
 * is the correct default for every other dialog in the console and the wrong
 * one for the only dialog whose contents cannot be recovered. The reader has to
 * press the button that says they have copied it.
 */
function SecretDialog({
  issued,
  onClose,
}: {
  issued: IssuedCredential;
  onClose: () => void;
}) {
  return (
    <Dialog
      title="Copy this secret now"
      onClose={onClose}
      confirmLabel="I have copied it"
      onConfirm={onClose}
      dismissible={false}
      wide
    >
      <Banner kind="warning">{issued.notice}</Banner>
      <CopyField label="Secret" value={issued.secret} />
      <p className="page__lede">
        It authenticates as <code>{issued.credential.visible_prefix}</code> and authorizes{' '}
        {issued.credential.scopes.join(', ')}.
      </p>
    </Dialog>
  );
}

/**
 * The two bodies, kept apart.
 *
 * `expires_in_days` is a literal union in the generated types — the server
 * offers 90, 180 or 365 and nothing else — so this is a `Select`, not a number
 * input that discovers the constraint by being refused.
 */
type CreateBody = S['CreateCredentialRequest'];
type RotateBody = S['RotateCredentialRequest'];
type IssueBody = CreateBody | RotateBody;

const EXPIRY_OPTIONS = [
  { value: '90', label: '90 days' },
  { value: '180', label: '180 days' },
  { value: '365', label: '365 days' },
] as const;

type ExpiryDays = CreateBody['expires_in_days'];

/**
 * Create and rotate share a dialog because they take the same decision: which
 * operations may this credential perform. Splitting them would be two copies of
 * the scope picker, and the scope picker is the part that must not drift.
 */
function IssueDialog<Body extends IssueBody>({
  title,
  lede,
  existing,
  build,
  action,
  onIssued,
  onClose,
}: {
  title: string;
  lede?: string;
  existing?: Credential;
  /** Turns what the reader picked into the body this endpoint takes. */
  build: (picked: { name: string; scopes: CreateBody['scopes']; days: ExpiryDays }) => Body;
  action: (body: Body) => Promise<IssuedCredential>;
  onIssued: (result: IssuedCredential) => void;
  onClose: () => void;
}) {
  const scopes = useQuery(scopesQuery);
  const [name, setName] = useState(existing ? existing.name : '');
  const [selected, setSelected] = useState<string[]>(existing ? [...existing.scopes] : []);
  const [days, setDays] = useState('90');
  const mutation = useCredentialMutation(action);
  const form = useSubmit<IssuedCredential>(
    (body: Body) => mutation.mutateAsync(body),
    onIssued,
  );

  return (
    <Dialog
      title={title}
      onClose={onClose}
      confirmLabel={existing ? 'Rotate' : 'Create'}
      confirmDisabled={selected.length === 0 || (!existing && name.trim() === '')}
      busy={form.pending}
      onConfirm={() =>
        form.submit(
          build({
            name: name.trim(),
            scopes: selected as CreateBody['scopes'],
            days: Number(days) as ExpiryDays,
          }),
        )
      }
      wide
    >
      {lede ? <p className="page__lede">{lede}</p> : null}
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}

      {existing ? null : (
        <Input
          label="Name"
          required
          value={name}
          error={form.fieldErrors.name}
          onChange={(event) => setName(event.target.value)}
          hint="How you will recognise it in this list. Not part of the secret."
        />
      )}

      <fieldset className="stack--tight">
        <legend>Authorizes</legend>
        <p className="gated__reason">
          Grant only what the integration performs. A credential that may write your catalogue
          because it was easier is a credential that can empty it.
        </p>
        <QueryState query={scopes} label="the operation list">
          {(data) =>
            data.scopes.map((scope) => (
              <label key={scope.scope} className="checkline">
                <input
                  type="checkbox"
                  checked={selected.includes(scope.scope)}
                  onChange={(event) =>
                    setSelected((current) =>
                      event.target.checked
                        ? [...current, scope.scope]
                        : current.filter((value) => value !== scope.scope),
                    )
                  }
                />
                <span>
                  {scope.label}
                  <span className="gated__reason"> {scope.scope}</span>
                </span>
              </label>
            ))
          }
        </QueryState>
      </fieldset>

      {existing ? null : (
        <Select
          label="Expires in"
          value={days}
          options={EXPIRY_OPTIONS}
          error={form.fieldErrors.expires_in_days}
          onChange={(event) => setDays(event.target.value)}
          hint="A credential that never expires is one nobody ever rotates."
        />
      )}
    </Dialog>
  );
}

function RevokeDialog({
  credential,
  onClose,
  onDone,
}: {
  credential: Credential;
  onClose: () => void;
  onDone: () => void;
}) {
  const mutation = useCredentialMutation(() => revokeCredential(credential.key_id));
  const form = useSubmit<void>(() => mutation.mutateAsync(undefined), onDone);

  return (
    <Dialog
      title={`Revoke ${credential.name}`}
      onClose={onClose}
      confirmLabel="Revoke"
      confirmVariant="danger"
      busy={form.pending}
      onConfirm={() => form.submit(undefined)}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <p>
        Anything authenticating as <code>{credential.visible_prefix}</code> stops working
        immediately. This cannot be undone — a revoked credential is not re-enabled, it is
        replaced.
      </p>
    </Dialog>
  );
}
