import { tenantStatus } from "../../api";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { Page } from "../../ui/Page";
import { Badge, ErrorBanner, Footnote, Skeleton } from "../../ui/primitives";

/** D-13: the workspace's lifecycle status. A member of a suspended workspace sees only this page. */
export function TenantStatusPage() {
  const status = useResource(() => tenantStatus.get(), []);
  const { signOutTenant } = useSession();
  const s = status.data;
  return <Page kicker="Workspace" title={s ? `${s.name}` : "Workspace status"}
    badge={s ? <Badge group="tenant" value={s.status} /> : undefined}
    subtitle={s?.message ?? "Checking the workspace status…"}
    actions={s?.restricted_session ? [{ label: "Sign out", onClick: signOutTenant }] : []}>
    {status.error ? <ErrorBanner error={status.error} onRetry={status.reload} /> : null}
    {!s && status.loading ? <Skeleton rows={2} /> : null}
    {s?.restricted_session ? <Footnote>
      Only a platform operator can change a workspace's status. Your account, data, models and credentials are kept;
      sign in again after the workspace is reactivated to get full access.
    </Footnote> : null}
  </Page>;
}
