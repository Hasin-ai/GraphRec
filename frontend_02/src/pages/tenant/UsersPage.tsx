import { useState } from "react";
import { tenantUsers } from "../../api";
import type { TenantUserInvitation, TenantUserResource, TenantUserRole } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, humanize } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Field, Select, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { ActionsCell, Banner, Cell, CopyButton, DataTable, ErrorBanner, Skeleton, Tag } from "../../ui/primitives";

function InviteDialog({ onClose, onDone }: { onClose: () => void; onDone: (user: TenantUserInvitation) => void }) {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState<TenantUserRole>('tenant_developer');
  return <Dialog title="Invite team member" body="Create an account in this tenant. Share the one-time setup link with the intended person after confirming their email."
    confirmLabel="Create invitation" onClose={onClose} onConfirm={async () => {
      if (!email.trim() || !email.includes('@')) return 'Enter a valid email address.';
      onDone(await tenantUsers.invite({ email: email.trim().toLowerCase(), role, ...(name.trim() ? { display_name: name.trim() } : {}) }));
    }}>
    <Field id="invite-email" label="Email"><TextInput id="invite-email" type="email" value={email} onChange={setEmail} autoComplete="off" /></Field>
    <Field id="invite-name" label="Display name (optional)"><TextInput id="invite-name" value={name} onChange={setName} /></Field>
    <Field id="invite-role" label="Role" hint={role === 'tenant_administrator' ? 'Administrators manage team members, training, models and usage as well as integrations.' : 'Developers manage integration credentials, catalog and events, and inspect training data. They cannot activate models or manage users.'}>
      <Select id="invite-role" value={role} onChange={value => setRole(value as TenantUserRole)} options={[{ value: 'tenant_developer', label: 'Tenant developer' }, { value: 'tenant_administrator', label: 'Tenant administrator' }]} />
    </Field>
  </Dialog>;
}

type Change = { user: TenantUserResource; kind: "role" | "lock" | "unlock" | "disable" };

const CHANGE_COPY: Record<Change["kind"], { title: string; body: string; confirm: string }> = {
  role: { title: "Change role", body: "The member is signed out everywhere and signs in again with the new role.", confirm: "Change role" },
  lock: { title: "Lock member", body: "The member is signed out everywhere and cannot sign in until unlocked.", confirm: "Lock member" },
  unlock: { title: "Unlock member", body: "The member can sign in again.", confirm: "Unlock member" },
  disable: { title: "Disable member", body: "The member is signed out and can never sign in again. The account is kept for audit; this cannot be undone.", confirm: "Disable member" },
};

function ChangeDialog({ change, onClose, onDone }: { change: Change; onClose: () => void; onDone: (user: TenantUserResource) => void }) {
  const { user, kind } = change;
  const [role, setRole] = useState<TenantUserRole>(user.role === "tenant_administrator" ? "tenant_developer" : "tenant_administrator");
  const [reason, setReason] = useState("");
  const copy = CHANGE_COPY[kind];
  return <Dialog title={`${copy.title}: ${user.email}`} body={copy.body} confirmLabel={copy.confirm} onClose={onClose} onConfirm={async () => {
    const status = kind === "lock" ? "locked" : kind === "unlock" ? "active" : kind === "disable" ? "disabled" : undefined;
    onDone(await tenantUsers.update(user.id, { ...(kind === "role" ? { role } : { status }), ...(reason.trim() ? { reason: reason.trim() } : {}) }));
  }}>
    {kind === "role" ? <Field id="member-role" label="New role">
      <Select id="member-role" value={role} onChange={value => setRole(value as TenantUserRole)} options={[{ value: 'tenant_developer', label: 'Tenant developer' }, { value: 'tenant_administrator', label: 'Tenant administrator' }]} />
    </Field> : null}
    <Field id="member-reason" label="Reason (optional)" hint="Stored in this tenant's audit trail."><TextInput id="member-reason" value={reason} onChange={setReason} /></Field>
  </Dialog>;
}

function rowActions(user: TenantUserResource, open: (change: Change) => void, resend: (user: TenantUserResource) => void, revoke: (user: TenantUserResource) => void) {
  if (user.status === "invited") return [{ label: "Resend invitation", onClick: () => resend(user) }, { label: "Revoke invitation", onClick: () => revoke(user) }];
  if (user.status === "disabled") return [];
  return [
    { label: "Change role", onClick: () => open({ user, kind: "role" }) },
    user.status === "locked" ? { label: "Unlock", onClick: () => open({ user, kind: "unlock" }) } : { label: "Lock", onClick: () => open({ user, kind: "lock" }) },
    { label: "Disable", onClick: () => open({ user, kind: "disable" }) },
  ];
}

export function UsersPage() {
  const users = useResource(() => tenantUsers.list(), []);
  const { flash } = useToast();
  const [inviting, setInviting] = useState(false);
  const [invitation, setInvitation] = useState<TenantUserInvitation | null>(null);
  const [revoking, setRevoking] = useState<TenantUserResource | null>(null);
  const [change, setChange] = useState<Change | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  async function resend(user: TenantUserResource) {
    setActionError(null);
    try { setInvitation(await tenantUsers.resendInvitation(user.id)); flash(`New invitation link created for ${user.email}. The previous link no longer works.`); }
    catch (caught) { setActionError(caught); }
  }
  const link = invitation ? `${window.location.origin}/invite/accept#token=${encodeURIComponent(invitation.setup_token)}` : '';
  return <Page title="Team members" subtitle="Manage who can access this tenant." crumbs={[{ label: 'Overview', to: '/home' }, { label: 'Team members' }]}
    actions={[{ label: 'Invite member', variant: 'primary', onClick: () => setInviting(true), disabled: !!invitation, reason: invitation ? 'Save the current invitation link first.' : undefined }, { label: 'Refresh', onClick: () => void users.reload(), disabled: users.loading }]}>
    {invitation ? <section className="stack">
      <Banner tone="warn" title="Save this invitation link">For {invitation.email}. Expires {fmtDateTime(invitation.setup_token_expires_at)}. This link is shown once and grants access to the invited account. No email has been sent.</Banner>
      <div className="snippet"><div className="s-head"><span>Account setup link</span><CopyButton value={link} label="Copy invitation link" /></div><pre data-testid="setup-link">{link}</pre></div>
      <div><button className="btn btn-primary" onClick={() => setInvitation(null)}>I have saved the invitation</button></div>
    </section> : null}
    {actionError ? <ErrorBanner error={actionError} /> : null}
    {users.error ? <ErrorBanner error={users.error} onRetry={users.reload} /> : null}
    {!users.data ? users.loading ? <Skeleton /> : null : <DataTable minWidth={820} columns={['Member', 'Role', 'Status', 'Invited', 'Last sign-in', { label: '', align: 'right' }]}
      rows={users.data.items.map(user => <tr key={user.id}><Cell sub={user.email}>{user.display_name}</Cell><Cell>{humanize(user.role)}</Cell><Cell><Tag tone={user.status === 'active' ? 'ok' : 'neu'}>{humanize(user.status)}</Tag></Cell><Cell>{fmtDateTime(user.created_at)}</Cell><Cell>{fmtDateTime(user.last_authenticated_at)}</Cell>{rowActions(user, setChange, user => void resend(user), setRevoking).length ? <ActionsCell actions={rowActions(user, setChange, user => void resend(user), setRevoking)} /> : <td />}</tr>)}
      count={`${users.data.total} members`} empty={{ title: 'No team members', body: 'Refresh to retrieve the current team.' }} />}
    {revoking ? <Dialog title={`Revoke invitation for ${revoking.email}`} body="The one-time setup link stops working immediately. The member is kept as disabled for audit." confirmLabel="Revoke invitation" onClose={() => setRevoking(null)} onConfirm={async () => { await tenantUsers.revokeInvitation(revoking.id); setRevoking(null); if (invitation?.id === revoking.id) setInvitation(null); void users.reload(); flash(`Invitation for ${revoking.email} revoked.`); }} /> : null}
    {change ? <ChangeDialog change={change} onClose={() => setChange(null)} onDone={user => { setChange(null); void users.reload(); flash(`${user.email} updated.`); }} /> : null}
    {inviting ? <InviteDialog onClose={() => setInviting(false)} onDone={user => { setInviting(false); setInvitation(user); void users.reload(); flash(`Invitation created for ${user.email}.`); }} /> : null}
  </Page>;
}
