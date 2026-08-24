import { useLoaderData, useRevalidator } from 'react-router-dom';
import { Badge, Button, DefinitionList } from '../../ui';
import type { TenantSummary } from '../../api/hooks/identity';

const EXPLANATION: Record<string, string> = {
  pending:
    'This organisation has been registered but not yet activated. A Platform Administrator ' +
    'reviews and activates it; nothing else here can be used until they do.',
  suspended:
    'A Platform Administrator has suspended this organisation. Sign-in still works so that you ' +
    'can see this page, but every other operation is refused until it is reinstated.',
  deleting:
    'This organisation is being removed. The work is irreversible and is already under way.',
  deleted: 'This organisation has been removed.',
};

const FALLBACK =
  'This organisation is not in a state that permits use. A Platform Administrator controls ' +
  'the transition.';

/**
 * `/account/tenant-status` — where gate 2 lands.
 *
 * It reads `GET /v1/tenant`, the one tenant-realm endpoint exempt from gate 2.
 * The exemption exists for this page: a status screen behind the gate that
 * sends people to it can never render, and the reader would be bounced between
 * a 403 and a redirect with nothing to read.
 *
 * The page states two things and no more — where the tenant is in its lifecycle,
 * and that a Platform Administrator controls the transition. There is no action
 * on it, because there is nothing a tenant user can do about it; offering a
 * button would suggest otherwise.
 */
export function TenantStatusRoute() {
  const tenant = useLoaderData() as TenantSummary;
  const revalidator = useRevalidator();
  const checking = revalidator.state === 'loading';

  return (
    <div className="gate">
      <h1 className="card__title">{tenant.tenant_name}</h1>
      <div className="gate__status">
        <Badge domain="tenant" value={tenant.status} />
      </div>
      <p className="card__lede">{EXPLANATION[tenant.status] ?? FALLBACK}</p>

      {tenant.status_reason ? (
        <p className="gate__reason">
          <strong>What the platform said: </strong>
          {tenant.status_reason}
        </p>
      ) : null}

      <div style={{ marginTop: 'var(--space-4)' }}>
        <DefinitionList
          items={[
            { term: 'Organisation code', value: <span className="mono">{tenant.tenant_code}</span> },
            { term: 'Plan', value: tenant.plan_code ?? '—' },
          ]}
        />
      </div>

      <div className="form-actions" style={{ marginTop: 'var(--space-5)' }}>
        <Button
          variant="secondary"
          loading={checking}
          disabled={checking}
          onClick={() => revalidator.revalidate()}
        >
          Check again
        </Button>
      </div>
    </div>
  );
}
