import { roleLabel, sessionTenantId } from "../../auth/session";
import { useSession, useTenant } from "../../hooks/useSession";
import { fmtDateTime } from "../../lib/format";
import { scopeLabel } from "../../lib/scopes";
import { Page } from "../../ui/Page";
import { Tag, Cell, DefinitionList, Footnote, Panel, PanelTable } from "../../ui/primitives";

const CAPABILITIES: [string, string][] = [
  ["Credential management", "keys:write"],
  ["User invitations", "users:write"],
  ["Catalog read", "catalog:read"],
  ["Catalog write & synchronization", "catalog:write"],
  ["Event submission", "events:write"],
  ["Submission result read", "events:read"],
  ["Training request", "training:write"],
  ["Training and snapshot read", "training:read"],
  ["Model version read", "models:read"],
  ["Model version write", "models:write"],
  ["Model activation and roll back", "models:deploy"],
  ["Recommendation serving", "recommendations:read"],
  ["Usage read", "usage:read"],
  ["Subscription read", "billing:read"],
  ["Deployment read", "deployments:read"],
  ["Serving metrics read", "metrics:read"],
];

/** Own record only: what the session carries. There is no profile or password-change endpoint. */
export function AccountPage() {
  const tenant = useTenant();
  const { signOutTenant } = useSession();
  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Account" }]}
      kicker="Your session"
      title="Account"
      subtitle="Your own record only, as carried by the current session. Scopes are granted at sign-in; sign in again after a role change."
      actions={[{ label: "Sign out", onClick: signOutTenant }]}
    >
      <DefinitionList
        items={[
          { label: "Tenant ID", value: sessionTenantId(tenant) ?? "Unavailable in this session", mono: true, copy: sessionTenantId(tenant) ?? undefined },
          { label: "Email", value: tenant.email || "Not provided during account setup", mono: true, copy: tenant.email || undefined },
          { label: "Role", value: roleLabel(tenant.role), mono: true },
          { label: "Signed in", value: fmtDateTime(tenant.signedInAt), mono: true },
          { label: "Session expires", value: fmtDateTime(tenant.expiresAt), mono: true },
        ]}
      />
      <Panel title="Capabilities of this session" body="Held scopes are the ones the login returned. A route or action outside them is refused by the API with 403 insufficient_scope.">
        <PanelTable
          columns={["Capability", "Scope", "Held"]}
          rows={CAPABILITIES.map(([label, scope]) => (
            <tr key={scope}>
              <Cell>{label}</Cell>
              <Cell mono muted>
                {scope}
              </Cell>
              <td>
                <Tag tone={tenant.scopes.includes(scope) ? "ok" : "neu"}>{tenant.scopes.includes(scope) ? "Granted" : "Not granted"}</Tag>
              </td>
            </tr>
          ))}
        />
        <p className="p-body">
          All granted: {tenant.scopes.map(scopeLabel).join(" · ")}
        </p>
      </Panel>
      <Footnote>Password changes and recovery are handled by an operator issuing a new setup token. See Recover access on the sign-in page.</Footnote>
    </Page>
  );
}
