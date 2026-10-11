import { roleLabel, sessionTenantId } from "../../auth/session";
import { useSession, useTenant } from "../../hooks/useSession";
import { fmtDateTime } from "../../lib/format";
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
      subtitle="Your sign-in details and what your role can do. Sign in again after your role changes."
      actions={[{ label: "Sign out", onClick: signOutTenant }]}
    >
      <DefinitionList
        items={[
          { label: "Email", value: tenant.email || "Not provided", copy: tenant.email || undefined },
          { label: "Role", value: roleLabel(tenant.role).replace(/^./, c => c.toUpperCase()) },
          { label: "Tenant ID", value: sessionTenantId(tenant) ?? "Not available", mono: !!sessionTenantId(tenant), copy: sessionTenantId(tenant) ?? undefined },
          { label: "Signed in", value: fmtDateTime(tenant.signedInAt) },
          { label: "Session expires", value: fmtDateTime(tenant.expiresAt) },
        ]}
      />
      <Panel title="What you can do" body={tenant.scopes.length >= CAPABILITIES.length ? `${roleLabel(tenant.role).replace(/^./, c => c.toUpperCase())}: full access to this tenant.` : `${roleLabel(tenant.role).replace(/^./, c => c.toUpperCase())}: ${CAPABILITIES.filter(([, sc]) => tenant.scopes.includes(sc)).length} of ${CAPABILITIES.length} permissions. Actions outside them are hidden or disabled.`}>
        <details className="details-section"><summary>View all permissions</summary>
        <PanelTable
          columns={["Permission", "Scope", "Access"]}
          rows={CAPABILITIES.map(([label, scope]) => (
            <tr key={scope}>
              <Cell>{label}</Cell>
              <Cell mono muted>
                {scope}
              </Cell>
              <td>
                {tenant.scopes.includes(scope) ? <span className="td-muted">Granted</span> : <Tag tone="warn">Not granted</Tag>}
              </td>
            </tr>
          ))}
        />
        </details>
      </Panel>
      <Footnote>To change your password, ask your platform operator for a recovery token, then use "Forgot password?" on the sign-in page.</Footnote>
    </Page>
  );
}
