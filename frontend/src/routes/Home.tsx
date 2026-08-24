import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTenantContext } from '../layouts/TenantLayout';
import { tenantNav } from '../layouts/nav';
import { onboardingQuery } from '../api/hooks/operations';
import type { Onboarding } from '../api/hooks/operations';
import { QueryState } from '../components/QueryState';

/**
 * `/home` — the onboarding checklist, then the permitted-services launcher.
 *
 * §7 is emphatic that this is a launcher and **not** an analytics dashboard:
 * no charts, no KPI tiles. It shows the modules this role may enter, which is
 * why an Administrator and a Developer see materially different pages, and it
 * derives that from the same table the sidebar uses so the two cannot disagree.
 *
 * The checklist is §5c's, and every tick in it is the server's answer from
 * `GET /v1/onboarding` (§10.9). Nothing here infers a step from another step:
 * the prototype could, holding the whole store; a real client that tried would
 * be reading five different moments and calling it a state.
 */
export function HomeRoute() {
  const { me, tenant } = useTenantContext();
  const role = me.role;
  const groups = tenantNav(role).filter((group) => group.label !== 'Workspace');
  const onboarding = useQuery(onboardingQuery);

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">{tenant.tenant_name}</h1>
        <p className="page__lede">
          What your role can reach. Anything not listed here is not yours to open, and the server
          refuses it independently of this page.
        </p>
      </div>

      <div className="stack">
        <section className="card">
          <h2 className="card__title">Getting to your first recommendation</h2>
          <QueryState
            query={onboarding}
            label="the setup checklist"
            isEmpty={(data: Onboarding) => data.steps.length === 0}
            empty={{
              headline: 'No checklist',
              body: 'The setup checklist is unavailable for this tenant.',
            }}
          >
            {(data) => <Checklist data={data} />}
          </QueryState>
        </section>

        {groups.map((group) => (
          <section key={group.label}>
            <h2 className="eyebrow">{group.label}</h2>
            <ul className="launcher">
              {group.items.map((item) => (
                <li key={item.to}>
                  <Link className="launcher__link" to={item.to}>
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

/**
 * A step nobody in this role can perform is still drawn, with its title as
 * plain text instead of a link.
 *
 * §5c calls this "not a wizard — every step is already a route", and the
 * corollary is that a developer must be able to see that the administrator has
 * not invited anybody yet. Hiding the step would leave them looking at a
 * complete-looking list and an integration that returns nothing.
 */
function Checklist({ data }: { data: Onboarding }) {
  return (
    <>
      <p className="checklist__progress">
        {data.completed} of {data.total} complete.
      </p>
      <ol className="checklist">
        {data.steps.map((step) => (
          <li
            key={step.key}
            className={`checklist__item${step.complete ? ' checklist__item--done' : ''}`}
          >
            <span className="checklist__mark" aria-hidden="true">
              {step.complete ? '✓' : '○'}
            </span>
            <div>
              <p className="checklist__title">
                {step.complete || !step.permitted ? (
                  step.title
                ) : (
                  <Link to={step.route}>{step.title}</Link>
                )}
                <span className="visually-hidden">
                  {step.complete ? ' — done' : ' — not started'}
                </span>
              </p>
              <p className="checklist__detail">
                {step.detail}
                {!step.permitted && !step.complete
                  ? ' A Tenant Administrator does this one.'
                  : null}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </>
  );
}
