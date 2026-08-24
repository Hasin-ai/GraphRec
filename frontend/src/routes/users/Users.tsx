/**
 * `/users` — the list, and the invite dialog.
 *
 * Administrator only, enforced by the loader (gate 3) rather than by not
 * drawing the sidebar link. §13 is explicit that a route is guarded by a route
 * guard and never by a hidden button, so a developer who types the address
 * gets `/403` rather than a page that happens to be empty.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { inviteUser, usersQuery, useUserMutation } from '../../api/hooks/operations';
import type { Invitation, TenantUser } from '../../api/hooks/operations';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { Badge, Banner, Button, CopyField, Dialog, FilterBar, Input, Select, Table } from '../../ui';
import type { Column } from '../../ui';
import { TENANT_ROLE_LABELS } from '../../lib/enums';
import type { TenantRole } from '../../lib/enums';
import { useSubmit } from '../../lib/useSubmit';
import { formatDate, formatDateTime } from '../../lib/format';

const ROLE_OPTIONS = [
  { value: 'tenant_administrator', label: TENANT_ROLE_LABELS.tenant_administrator },
  { value: 'tenant_developer', label: TENANT_ROLE_LABELS.tenant_developer },
] as const;

const STATUS_OPTIONS = [
  { value: 'invited', label: 'invited' },
  { value: 'active', label: 'active' },
  { value: 'locked', label: 'locked' },
  { value: 'disabled', label: 'disabled' },
] as const;

export function UsersRoute() {
  const users = useQuery(usersQuery);
  const [role, setRole] = useState('');
  const [status, setStatus] = useState('');
  const [inviting, setInviting] = useState(false);
  const [issued, setIssued] = useState<Invitation | null>(null);

  const columns: readonly Column<TenantUser>[] = [
    {
      key: 'name',
      header: 'Name',
      cell: (row) => <Link to={`/users/${row.tenant_user_id}`}>{row.display_name}</Link>,
    },
    { key: 'email', header: 'Email', cell: (row) => row.email },
    {
      key: 'role',
      header: 'Role',
      cell: (row) => TENANT_ROLE_LABELS[row.role as TenantRole] ?? row.role,
    },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => <Badge domain="user" value={row.status} />,
    },
    { key: 'created', header: 'Created', cell: (row) => formatDate(row.created_at) },
    {
      key: 'seen',
      header: 'Last signed in',
      cell: (row) => formatDateTime(row.last_authenticated_at),
    },
  ];

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Users</h1>
        <p className="page__lede">
          Who may sign in to this organisation, and what each of them may do. Inviting somebody
          creates their account immediately; they choose their own password when they accept.
        </p>
      </div>

      <p className="action-row">
        <Button onClick={() => setInviting(true)}>Invite user</Button>
      </p>

      <FilterBar
        onReset={
          role || status
            ? () => {
                setRole('');
                setStatus('');
              }
            : undefined
        }
      >
        <Select
          label="Role"
          value={role}
          placeholder="Any role"
          options={ROLE_OPTIONS}
          onChange={(event) => setRole(event.target.value)}
        />
        <Select
          label="Status"
          value={status}
          placeholder="Any status"
          options={STATUS_OPTIONS}
          onChange={(event) => setStatus(event.target.value)}
        />
      </FilterBar>

      <QueryState
        query={users}
        shape="table"
        columns={columns.length}
        label="the user list"
        isEmpty={(data) => data.users.length === 0}
        empty={{
          headline: 'No users',
          body: 'This cannot happen — the tenant has at least its registering administrator. If you are seeing it, reload.',
        }}
      >
        {(data) => {
          // Filtering here rather than on the server: `GET /v1/users` is not
          // paginated because a tenant's user count is bounded by how many
          // people work there, so the whole list is already in hand and a round
          // trip per keystroke would buy nothing.
          const rows = data.users.filter(
            (user) =>
              (!role || user.role === role) && (!status || user.status === status),
          );
          return (
            <>
              <p className="checklist__progress">
                {rows.length} of {data.total}
              </p>
              <Table
                caption="Users in this tenant"
                columns={columns}
                rows={rows}
                rowKey={(row) => row.tenant_user_id}
                empty="No user matches those filters."
              />
            </>
          );
        }}
      </QueryState>

      {inviting ? (
        <InviteDialog
          onClose={() => setInviting(false)}
          onIssued={(result) => {
            setInviting(false);
            setIssued(result);
          }}
        />
      ) : null}

      {issued ? <InvitationDialog issued={issued} onClose={() => setIssued(null)} /> : null}
    </div>
  );
}

function InviteDialog({
  onClose,
  onIssued,
}: {
  onClose: () => void;
  onIssued: (result: Invitation) => void;
}) {
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [role, setRole] = useState<string>('tenant_developer');
  const mutation = useUserMutation(inviteUser);
  const form = useSubmit<Invitation>(
    (body: S['CreateUserRequest']) => mutation.mutateAsync(body),
    onIssued,
  );

  return (
    <Dialog
      title="Invite user"
      onClose={onClose}
      confirmLabel="Send invitation"
      busy={form.pending}
      confirmDisabled={email.trim() === ''}
      onConfirm={() =>
        form.submit({
          email: email.trim(),
          display_name: displayName.trim() || email.trim(),
          role: role as S['CreateUserRequest']['role'],
        })
      }
    >
      {/* A duplicate address is a *conflict*, not a validation error (§5b), and
          the server says so with its own sentence — this renders it verbatim. */}
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <Input
        label="Email"
        type="email"
        required
        value={email}
        error={form.fieldErrors.email}
        onChange={(event) => setEmail(event.target.value)}
        hint="This is their account identifier, and it cannot be changed later."
      />
      <Input
        label="Display name"
        value={displayName}
        error={form.fieldErrors.display_name}
        onChange={(event) => setDisplayName(event.target.value)}
      />
      <Select
        label="Role"
        required
        value={role}
        options={ROLE_OPTIONS}
        error={form.fieldErrors.role}
        onChange={(event) => setRole(event.target.value)}
        hint="A developer integrates the API. An administrator also manages users, the catalogue and the model."
      />
    </Dialog>
  );
}

/**
 * The invitation token, shown once — the same rule as a credential secret, and
 * for the same reason: only its digest was stored.
 *
 * Unlike a credential secret this one is *meant* to be passed on, because there
 * is no mail transport (ADR 0032, BUILD_PROMPT L90) and the administrator is
 * the delivery mechanism. That is stated on the dialog rather than left for
 * them to work out from the fact that nothing arrived.
 */
function InvitationDialog({
  issued,
  onClose,
}: {
  issued: Invitation;
  onClose: () => void;
}) {
  return (
    <Dialog
      title={`Send this link to ${issued.user.display_name}`}
      onClose={onClose}
      confirmLabel="I have sent it"
      onConfirm={onClose}
      dismissible={false}
      wide
    >
      <Banner kind="warning">
        This link is shown once and is not stored. Nothing is emailed — pass it on yourself, over a
        channel you trust. If it is lost, resend the invitation from their user page.
      </Banner>
      <CopyField
        label="Invitation link"
        value={`${window.location.origin}/invite/accept?token=${encodeURIComponent(issued.invitation_token)}`}
      />
      <p className="page__lede">It expires {formatDateTime(issued.expires_at)}.</p>
    </Dialog>
  );
}
