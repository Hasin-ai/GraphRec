import { useState } from "react";
import { platform } from "../../api";
import type { PlatformOperator } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Field, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { ActionsCell, Cell, DataTable, ErrorBanner, Footnote, Skeleton, Tag } from "../../ui/primitives";

type Role = PlatformOperator["roles"][number];
const ROLES: { role: Role; label: string; detail: string }[] = [
  { role: "platform", label: "Platform", detail: "Tenant status and account recovery" },
  { role: "plan_management", label: "Plan management", detail: "Plans, plan assignment and quota overrides" },
  { role: "monitoring", label: "Monitoring", detail: "Platform status, failures and tenant usage" },
  { role: "audit", label: "Audit", detail: "The full audit history" },
  { role: "operator_admin", label: "Operator admin", detail: "Create operators and change their roles" },
];

function RolePicker({ value, onChange }: { value: Role[]; onChange: (roles: Role[]) => void }) {
  return <fieldset className="role-picker"><legend>Roles</legend>
    {ROLES.map(r => <label key={r.role} className="check">
      <input type="checkbox" checked={value.includes(r.role)} onChange={e => onChange(e.target.checked ? [...value, r.role] : value.filter(x => x !== r.role))} />
      <span><strong>{r.label}</strong> <span className="muted small">{r.detail}</span></span>
    </label>)}
  </fieldset>;
}

function CreateOperatorDialog({ onClose, onDone }: { onClose: () => void; onDone: (o: PlatformOperator) => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState<Role[]>(["monitoring"]);
  return <Dialog title="Add operator" width={620} confirmLabel="Add operator"
    body="The operator signs in at /admin/login with this email and password. Share the password through a trusted channel; they can be given a new one here."
    onClose={onClose} onConfirm={async () => {
      if (!email.trim() || !name.trim()) return "Enter an email and a name.";
      if (password.length < 12) return "The password must be at least 12 characters.";
      if (!roles.length) return "Choose at least one role.";
      onDone(await platform.createOperator({ email: email.trim(), display_name: name.trim(), password, roles }));
    }}>
    <Field id="op-email" label="Email"><TextInput id="op-email" type="email" value={email} onChange={setEmail} autoComplete="off" required /></Field>
    <Field id="op-name" label="Name"><TextInput id="op-name" value={name} onChange={setName} required /></Field>
    <Field id="op-password" label="Initial password" hint="At least 12 characters."><TextInput id="op-password" type="password" value={password} onChange={setPassword} autoComplete="new-password" required /></Field>
    <RolePicker value={roles} onChange={setRoles} />
  </Dialog>;
}

function RolesDialog({ operator, onClose, onDone }: { operator: PlatformOperator; onClose: () => void; onDone: (o: PlatformOperator) => void }) {
  const [roles, setRoles] = useState<Role[]>(operator.roles);
  return <Dialog title={`Roles for ${operator.display_name}`} width={620} confirmLabel="Save roles"
    body="Changing roles signs the operator out of current sessions." onClose={onClose}
    onConfirm={async () => roles.length ? onDone(await platform.updateOperator(operator.id, { roles })) : "Choose at least one role."}>
    <RolePicker value={roles} onChange={setRoles} />
  </Dialog>;
}

/** D-04: named operators and their roles. Operators are disabled, never deleted, so audit attribution keeps resolving. */
export function PlatformOperatorsPage() {
  const operators = useResource(() => platform.listOperators(), []);
  const { platform: session } = useSession();
  const { flash } = useToast();
  const [dialog, setDialog] = useState<null | "create" | PlatformOperator>(null);
  const replace = (o: PlatformOperator) => operators.setData(prev => prev ? { items: prev.items.some(x => x.id === o.id) ? prev.items.map(x => x.id === o.id ? o : x) : [...prev.items, o] } : prev);
  const rows = (operators.data?.items ?? []).map(o => <tr key={o.id}>
    <Cell>{o.display_name}<div className="sub mono">{o.email}</div></Cell>
    <Cell muted>{o.roles.map(r => ROLES.find(x => x.role === r)?.label ?? r).join(", ")}</Cell>
    <td><Tag tone={o.status === "active" ? "ok" : "neu"}>{o.status}</Tag></td>
    <Cell muted>{o.last_login_at ? fmtDateTime(o.last_login_at) : "Never"}</Cell>
    <ActionsCell actions={o.email === session?.email ? [] : [
      { label: "Edit roles", onClick: () => setDialog(o) },
      { label: o.status === "active" ? "Disable" : "Enable", onClick: async () => {
        const updated = await platform.updateOperator(o.id, { status: o.status === "active" ? "disabled" : "active" });
        replace(updated); flash(`${updated.display_name} is now ${updated.status}.`);
      } },
    ]} />
  </tr>);
  return <Page crumbs={[{ label: "Platform", to: "/admin/status" }, { label: "Operators" }]} kicker="Operator admin" title="Operators"
    subtitle="People who can operate the platform. Every operator action is recorded under the operator's name."
    actions={[{ label: "Add operator", variant: "primary", onClick: () => setDialog("create") }]}>
    {operators.error ? <ErrorBanner error={operators.error} onRetry={operators.reload} /> : null}
    {!operators.data ? (operators.loading ? <Skeleton /> : null) :
      <DataTable minWidth={760} columns={["Operator", "Roles", "Status", "Last sign-in", { label: "", align: "right" }]} rows={rows}
        count={`${rows.length} operators`} empty={{ title: "No operators yet", body: "Add the first operator. Until one exists, production accepts the bootstrap token only to create operators." }} />}
    <Footnote>Disabling an operator, changing roles or setting a new password ends that operator's sessions immediately.</Footnote>
    {dialog === "create" ? <CreateOperatorDialog onClose={() => setDialog(null)} onDone={o => { replace(o); setDialog(null); flash(`${o.display_name} added.`); }} /> : null}
    {dialog && dialog !== "create" ? <RolesDialog operator={dialog} onClose={() => setDialog(null)} onDone={o => { replace(o); setDialog(null); flash(`Roles updated for ${o.display_name}.`); }} /> : null}
  </Page>;
}
