import { useState } from "react";
import { apiKeys } from "../../api";
import type { ApiKeyResource, ApiKeyScope, ApiKeySecretResource } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useTenant } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime } from "../../lib/format";
import { API_KEY_SCOPES, SCOPE_SHORT, delegatableScopes } from "../../lib/scopes";
import { Dialog, SecretDialog } from "../../ui/Dialog";
import { CheckGroup, Field, Select, TextArea, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { ActionsCell, Badge, Cell, DataTable, ErrorBanner, Skeleton } from "../../ui/primitives";

type DialogState = { kind: "create" } | { kind: "rotate"; key: ApiKeyResource } | { kind: "revoke"; key: ApiKeyResource } | null;

const EXPIRY_OPTIONS = [
  { value: "", label: "No expiry" },
  { value: "90", label: "90 days" },
  { value: "180", label: "180 days" },
  { value: "365", label: "365 days" },
];

function expiryFromDays(days: string): string | null {
  if (!days) return null;
  return new Date(Date.now() + Number(days) * 86_400_000).toISOString();
}

function CreateDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (secret: ApiKeySecretResource) => void }) {
  const tenant = useTenant();
  const allowed = delegatableScopes(tenant.role);
  const [name, setName] = useState("");
  const [expiry, setExpiry] = useState("90");
  const [scopes, setScopes] = useState<string[]>([allowed[0]]);

  async function confirm() {
    if (!name.trim()) return "Give the credential a name so it can be told apart in this list.";
    if (!scopes.length) return "Select at least one integration operation. A credential with no scope cannot authorize anything.";
    onCreated(await apiKeys.create({ name: name.trim(), scopes: scopes as ApiKeyScope[], expires_at: expiryFromDays(expiry) }));
  }

  return (
    <Dialog title="Create credential" width={640} confirmLabel="Create credential" body="The secret is shown once on the next screen and is never retained by GraphRec." onConfirm={confirm} onClose={onClose}>
      <Field id="d-name" label="Credential name">
        <TextInput id="d-name" value={name} onChange={setName} placeholder="Storefront server" />
      </Field>
      <Field id="d-expiry" label="Expiry">
        <Select id="d-expiry" value={expiry} onChange={setExpiry} options={EXPIRY_OPTIONS} />
      </Field>
      <Field id="d-scopes" label="Allowed integration operations" hint={tenant.role === "tenant_developer" ? "A developer may delegate catalog and event scopes only." : undefined}>
        <CheckGroup options={API_KEY_SCOPES.filter((s) => allowed.includes(s.scope)).map((s) => ({ value: s.scope, label: s.label }))} value={scopes} onChange={setScopes} />
      </Field>
    </Dialog>
  );
}

function RotateDialog({ apiKey, onClose, onRotated }: { apiKey: ApiKeyResource; onClose: () => void; onRotated: (secret: ApiKeySecretResource) => void }) {
  const [grace, setGrace] = useState("3600");
  const [reason, setReason] = useState("");

  async function confirm() {
    if (reason.trim().length < 4) return "A reason is required for this action.";
    onRotated(await apiKeys.rotate(apiKey.id, { grace_period_seconds: Number(grace), reason: reason.trim() }));
  }

  return (
    <Dialog
      title={`Rotate ${apiKey.name}`}
      width={640}
      confirmLabel="Rotate credential"
      body="Rotation issues a new secret. The current secret keeps working for the grace period, then fails authentication."
      consequence="Scopes are unchanged by rotation. Create a new credential to change what an integration may do."
      facts={[
        { label: "Prefix", value: `${apiKey.prefix}…` },
        { label: "Scopes", value: apiKey.scopes.map((s) => SCOPE_SHORT[s] ?? s).join(" · ") },
      ]}
      onConfirm={confirm}
      onClose={onClose}
    >
      <Field id="d-grace" label="Grace period for the old secret">
        <Select
          id="d-grace"
          value={grace}
          onChange={setGrace}
          options={[
            { value: "0", label: "None: old secret stops immediately" },
            { value: "3600", label: "1 hour" },
            { value: "21600", label: "6 hours" },
            { value: "86400", label: "24 hours (maximum)" },
          ]}
        />
      </Field>
      <Field id="d-reason" label="Reason">
        <TextArea id="d-reason" rows={3} value={reason} onChange={setReason} placeholder="Scheduled rotation" />
      </Field>
    </Dialog>
  );
}

export function CredentialsPage() {
  const keys = useResource(() => apiKeys.list(), []);
  const { flash } = useToast();
  const [dialog, setDialog] = useState<DialogState>(null);
  const [secret, setSecret] = useState<{ title: string; value: ApiKeySecretResource } | null>(null);

  // Mutation responses are the authoritative row: apply them locally rather than
  // re-listing, which would spend the API-key administrative rate limit (10/min).
  function upsertRow(row: ApiKeyResource) {
    keys.setData((prev) => {
      const items = prev?.items ?? [];
      const known = items.some((k) => k.id === row.id);
      return { items: known ? items.map((k) => (k.id === row.id ? row : k)) : [row, ...items] };
    });
  }

  function showSecret(title: string, value: ApiKeySecretResource) {
    setDialog(null);
    setSecret({ title, value });
    const { secret: _secret, ...row } = value;
    upsertRow(row);
  }

  const rows = (keys.data?.items ?? []).map((k) => (
    <tr key={k.id}>
      <Cell>{k.name}</Cell>
      <Cell mono sub={k.status !== "active" ? "cannot authorize" : k.grace_expires_at ? `previous secret valid until ${fmtDateTime(k.grace_expires_at)}` : undefined}>
        {k.prefix}…
      </Cell>
      <Cell muted sub={k.scopes.map((s) => SCOPE_SHORT[s] ?? s).join(" · ")}>
        {k.scopes.length} operations
      </Cell>
      <Cell mono>{fmtDateTime(k.expires_at)}</Cell>
      <Cell mono>{fmtDateTime(k.revoked_at)}</Cell>
      <Cell mono>{fmtDateTime(k.last_used_at)}</Cell>
      <td>
        <Badge group="key" value={k.status} />
      </td>
      <ActionsCell
        actions={[
          { label: "Rotate", disabled: k.status === "revoked", reason: k.status === "revoked" ? "Revoked credentials cannot be rotated." : undefined, onClick: () => setDialog({ kind: "rotate", key: k }) },
          { label: "Revoke", disabled: k.status === "revoked", onClick: () => setDialog({ kind: "revoke", key: k }) },
        ]}
      />
    </tr>
  ));

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "API Credentials" }]}
      kicker="Integration identity"
      title="API Credentials"
      subtitle="Credentials authenticate your e-commerce application server-to-server. The secret is displayed once, at creation or rotation, and is not retained."
      actions={[{ label: "Create credential", variant: "primary", onClick: () => setDialog({ kind: "create" }) }]}
    >
      {keys.error ? <ErrorBanner error={keys.error} /> : null}
      {keys.loading && !keys.data ? (
        <Skeleton />
      ) : (
        <DataTable
          minWidth={1080}
          columns={["Name", "Prefix", "Allowed operations", "Expires", "Revoked at", "Last used", "Authorizes", { label: "", align: "right" }]}
          rows={rows}
          count={`${rows.length} of ${rows.length}`}
          empty={{ title: "No credentials yet", body: "Create a credential so your application can authenticate.", action: { label: "Create credential", onClick: () => setDialog({ kind: "create" }) } }}
        />
      )}

      {dialog?.kind === "create" ? <CreateDialog onClose={() => setDialog(null)} onCreated={(s) => showSecret("Credential created", s)} /> : null}
      {dialog?.kind === "rotate" ? <RotateDialog apiKey={dialog.key} onClose={() => setDialog(null)} onRotated={(s) => showSecret("Credential rotated", s)} /> : null}
      {dialog?.kind === "revoke" ? (
        <Dialog
          title={`Revoke ${dialog.key.name}`}
          confirmLabel="Revoke"
          body="Revocation takes effect immediately and cannot be undone."
          consequence="Any request presenting this credential will fail authentication. Issue a replacement before revoking if the integration is live."
          facts={[
            { label: "Prefix", value: `${dialog.key.prefix}…` },
            { label: "Last used", value: fmtDateTime(dialog.key.last_used_at) },
          ]}
          onConfirm={async () => {
            const revoked = await apiKeys.revoke(dialog.key.id);
            setDialog(null);
            flash(`Credential ${dialog.key.name} revoked.`);
            upsertRow(revoked);
          }}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {secret ? (
        <SecretDialog title={secret.title} secret={secret.value.secret} prefix={secret.value.prefix} scopes={`${secret.value.scopes.length} operations`} onClose={() => setSecret(null)} />
      ) : null}
    </Page>
  );
}
