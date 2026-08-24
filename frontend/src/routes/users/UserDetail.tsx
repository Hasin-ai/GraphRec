/**
 * `/users/:userId` — one user, and the three things an administrator can do to
 * them: change the role, change the status, resend the invitation.
 *
 * The last-administrator rule is not re-implemented here. The server sends
 * `is_last_active_administrator` (§10.9) and both controls are disabled from
 * it, with the sentence the server would have refused with. Deriving it in the
 * browser would mean counting administrators from a list this page does not
 * load, and getting a different answer the moment somebody else acts.
 */

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  changeUserRole,
  changeUserStatus,
  resendInvitation,
  userQuery,
  useUserMutation,
} from '../../api/hooks/operations';
import type { Invitation, TenantUser } from '../../api/hooks/operations';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { GatedAction } from '../../components/gate5';
import { Badge, Banner, Breadcrumbs, CopyField, DefinitionList, Dialog, Select } from '../../ui';
import { TENANT_ROLE_LABELS } from '../../lib/enums';
import type { TenantRole } from '../../lib/enums';
import { useSubmit } from '../../lib/useSubmit';
import { formatDateTime } from '../../lib/format';

const ROLE_OPTIONS = [
  { value: 'tenant_administrator', label: TENANT_ROLE_LABELS.tenant_administrator },
  { value: 'tenant_developer', label: TENANT_ROLE_LABELS.tenant_developer },
];

/**
 * Which statuses an administrator may move somebody to by hand.
 *
 * §5b lists lock, unlock, disable and re-enable as four dialogs. They are one
 * control here because they are one field with three destinations, and four
 * buttons that all `PATCH /status` would be four ways to be told the same
 * refusal. `invited` is absent because it is not a destination — it is where
 * an account starts, and it ends when the invitation is accepted.
 */
const STATUS_OPTIONS = [
  { value: 'active', label: 'Active — may sign in' },
  { value: 'locked', label: 'Locked — temporarily barred, can be unlocked' },
  { value: 'disabled', label: 'Disabled — may not sign in' },
];

export function UserDetailRoute() {
  const { userId = '' } = useParams();
  const query = useQuery(userQuery(userId));

  return (
    <div className="page">
      <Breadcrumbs
        crumbs={[
          { label: 'Users', to: '/users' },
          { label: query.data?.display_name ?? 'User' },
        ]}
      />
      <QueryState query={query} label="this user">
        {(user) => <UserPanel user={user} />}
      </QueryState>
    </div>
  );
}

function UserPanel({ user }: { user: TenantUser }) {
  const [dialog, setDialog] = useState<'role' | 'status' | null>(null);
  const [issued, setIssued] = useState<Invitation | null>(null);
  const resend = useUserMutation((id: string) => resendInvitation(id));

  // One sentence, used by both controls, phrased the way the server refuses.
  const lastAdmin = user.is_last_active_administrator
    ? 'This is the last active administrator. Promote somebody else first — a tenant without one cannot manage itself.'
    : null;

  return (
    <>
      <div className="page__head">
        <h1 className="page__title">{user.display_name}</h1>
        <p className="page__lede">{user.email}</p>
      </div>

      <DefinitionList
        items={[
          { term: 'Role', value: TENANT_ROLE_LABELS[user.role as TenantRole] ?? user.role },
          { term: 'Status', value: <Badge domain="user" value={user.status} /> },
          { term: 'Created', value: formatDateTime(user.created_at) },
          { term: 'Last signed in', value: formatDateTime(user.last_authenticated_at) },
        ]}
      />

      {user.status === 'invited' ? (
        <Banner kind="info">
          This invitation has not been accepted yet. Resending issues a fresh link and invalidates
          the old one — the original cannot be re-sent, because only its digest was kept.
        </Banner>
      ) : null}

      <div className="action-row">
        <GatedAction
          label="Change role"
          allowed={!user.is_last_active_administrator}
          reason={lastAdmin}
          onClick={() => setDialog('role')}
        />
        <GatedAction
          label="Change status"
          allowed={!user.is_last_active_administrator}
          reason={lastAdmin}
          variant="secondary"
          onClick={() => setDialog('status')}
        />
        <GatedAction
          label="Resend invitation"
          allowed={user.status === 'invited'}
          reason="Only an unaccepted invitation can be resent. This account is already in use."
          variant="secondary"
          busy={resend.isPending}
          onClick={() => {
            void resend.mutateAsync(user.tenant_user_id).then(setIssued);
          }}
        />
      </div>

      {dialog === 'role' ? (
        <ChangeDialog
          title="Change role"
          label="Role"
          options={ROLE_OPTIONS}
          initial={user.role}
          hint="Demoting the last administrator is refused by the server, not just by this page."
          action={(value) =>
            changeUserRole(user.tenant_user_id, { role: value as S['TenantRole'] })
          }
          onClose={() => setDialog(null)}
        />
      ) : null}

      {dialog === 'status' ? (
        <ChangeDialog
          title="Change status"
          label="Status"
          options={STATUS_OPTIONS}
          initial={user.status === 'invited' ? 'active' : user.status}
          hint="Disabling somebody ends their sessions at their next request; it does not delete anything they created."
          action={(value) =>
            changeUserStatus(user.tenant_user_id, { status: value as S['UserStatus'] })
          }
          onClose={() => setDialog(null)}
        />
      ) : null}

      {issued ? (
        <Dialog
          title="New invitation link"
          onClose={() => setIssued(null)}
          confirmLabel="I have sent it"
          onConfirm={() => setIssued(null)}
          dismissible={false}
          wide
        >
          <Banner kind="warning">
            Shown once. Pass it on yourself — nothing is emailed. The previous link no longer works.
          </Banner>
          <CopyField
            label="Invitation link"
            value={`${window.location.origin}/invite/accept?token=${encodeURIComponent(issued.invitation_token)}`}
          />
          <p className="page__lede">It expires {formatDateTime(issued.expires_at)}.</p>
        </Dialog>
      ) : null}
    </>
  );
}

/** Role and status differ only in their vocabulary, so they share a dialog. */
function ChangeDialog({
  title,
  label,
  options,
  initial,
  hint,
  action,
  onClose,
}: {
  title: string;
  label: string;
  options: { value: string; label: string }[];
  initial: string;
  hint: string;
  action: (value: string) => Promise<TenantUser>;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initial);
  const mutation = useUserMutation(action);
  const form = useSubmit<TenantUser>((next: string) => mutation.mutateAsync(next), onClose);

  return (
    <Dialog
      title={title}
      onClose={onClose}
      confirmLabel="Save"
      busy={form.pending}
      confirmDisabled={value === initial}
      onConfirm={() => form.submit(value)}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <Select
        label={label}
        value={value}
        options={options}
        hint={hint}
        onChange={(event) => setValue(event.target.value)}
      />
    </Dialog>
  );
}
