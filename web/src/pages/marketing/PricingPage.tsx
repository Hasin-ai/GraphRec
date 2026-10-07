import { Link } from "react-router-dom";
import { useSession } from "../../hooks/useSession";
import { LIMIT_KEYS, MONTHLY_LIMITS, formatLimit, limitLabel, type MarketingPlan } from "../../marketing/plans";
import { useLivePlans } from "../../marketing/useLivePlans";
import { useDocumentTitle } from "../../marketing/useDocumentTitle";

const CARD_LIMITS = ["accepted_events", "recommendation_requests", "stored_products", "training_jobs", "active_model_versions"] as const;
const OPERATOR_NOTE = "Every tenant starts on Free. A platform operator moves you to Basic or Pro.";

function PlanCta({ plan }: { plan: MarketingPlan }) {
  const { tenant, platform } = useSession();
  if (tenant) return <Link className="btn btn-secondary" to="/usage">View your usage</Link>;
  if (platform) return <Link className="btn btn-secondary" to="/admin/plans">Manage plans</Link>;
  return plan.code === "free"
    ? <Link className="btn btn-primary" to="/register">Create a tenant</Link>
    : <>
        <Link className="btn btn-secondary" to="/register">Start on Free</Link>
        <p className="mkt-plan-note">{OPERATOR_NOTE}</p>
      </>;
}

const FAQ: { q: string; a: string }[] = [
  { q: "What counts as an accepted event?",
    a: "An interaction event that passes validation and is stored for your tenant. Sending the same event again is confirmed as a duplicate, not counted twice, so retries are safe. Rejected events do not count either." },
  { q: "What happens when I reach a limit?",
    a: "Requests that would go over the limit are rejected with a clear quota error that names the limit, so nothing is dropped silently. The Usage & Quotas page in the console shows each limit, how much you have used, and which limits are near capacity." },
  { q: "Do limits reset every month?",
    a: "Accepted events, recommendation requests and training jobs are counted per calendar month (UTC) and reset at the start of the next one. Stored products, active model versions and artifact storage are standing totals; requests per minute and concurrency limits apply continuously." },
  { q: "How do I change plans?",
    a: "Plans are assigned by your GraphRec platform operator. Every tenant starts on Free; ask your operator to move you to Basic or Pro. The new limits apply immediately and your usage is not reset." },
  { q: "Is there a payment flow?",
    a: "No. Plans carry no prices, and GraphRec has no checkout and collects no payments. Plans set capacity only." },
];

/** `/pricing`: always reachable, signed in or not. Limits are read live from `GET /v1/plans`. */
export function PricingPage() {
  useDocumentTitle("Pricing · GraphRec");
  const { tenant } = useSession();
  const { plans, live } = useLivePlans();
  return <>
    <section className="mkt-page-head" aria-labelledby="pricing-title">
      <div className="mkt-container">
        <p className="mkt-kicker">Pricing</p>
        <h1 id="pricing-title">Plans and limits</h1>
        <p className="mkt-lede">Every plan includes the whole platform. Plans differ only in capacity: how many events, requests, products and training runs your tenant can use.</p>
      </div>
    </section>

    <section className="mkt-section mkt-section-tight" aria-labelledby="plans-title">
      <div className="mkt-container">
        <h2 id="plans-title" className="sr-only">Plans</h2>
        {live ? null : <p className="mkt-plan-note" role="status">Showing the default plan limits. Your operator may have changed them.</p>}
        <ul className="mkt-plans">
          {plans.map(plan => <li key={plan.code} className={`mkt-card mkt-plan${plan.code === "basic" ? " is-marked" : ""}`}>
            <div className="mkt-plan-head">
              <h3>{plan.name}</h3>
              {plan.code === "basic" ? <span className="tag mkt-tag">Room to grow</span> : null}
            </div>
            <p className="mkt-plan-tagline">{plan.tagline}</p>
            <p className={`mkt-price${plan.price === null && plan.code !== "free" ? " is-assigned" : ""}`}>{plan.code === "free" ? "Free" : "Assigned by your platform operator"}</p>
            <dl className="mkt-limits">
              {CARD_LIMITS.map(key => <div key={key}>
                <dt>{limitLabel(key)}{MONTHLY_LIMITS.has(key) ? " / month" : ""}</dt>
                <dd className="mono">{formatLimit(key, plan.limits[key])}</dd>
              </div>)}
            </dl>
            <div className="mkt-plan-cta"><PlanCta plan={plan} /></div>
          </li>)}
        </ul>
        {tenant ? <p className="mkt-more">Your current plan and usage are on the <Link to="/usage">Usage &amp; Quotas</Link> page.</p> : null}
      </div>
    </section>

    <section className="mkt-section mkt-section-tight" aria-labelledby="compare-title">
      <div className="mkt-container">
        <h2 id="compare-title">Compare every limit</h2>
        <p className="table-scroll-hint">Scroll sideways to see every plan.</p>
        <div className="mkt-table-wrap" role="region" aria-labelledby="compare-caption" tabIndex={0}>
          <table className="mkt-compare">
            <caption id="compare-caption">Seeded plan limits. A platform operator can change them at runtime.</caption>
            <thead>
              <tr><th scope="col">Limit</th>{plans.map(plan => <th key={plan.code} scope="col" className="num">{plan.name}</th>)}</tr>
            </thead>
            <tbody>
              {LIMIT_KEYS.map(key => <tr key={key}>
                <th scope="row">{limitLabel(key)}{MONTHLY_LIMITS.has(key) ? <span className="mkt-unit">per calendar month</span> : null}</th>
                {plans.map(plan => <td key={plan.code} className="num">{formatLimit(key, plan.limits[key])}</td>)}
              </tr>)}
            </tbody>
          </table>
        </div>
      </div>
    </section>

    <section className="mkt-section" aria-labelledby="faq-title">
      <div className="mkt-container mkt-faq-wrap">
        <h2 id="faq-title">Questions</h2>
        <div className="mkt-faq">
          {FAQ.map(item => <details key={item.q}><summary>{item.q}</summary><p>{item.a}</p></details>)}
        </div>
      </div>
    </section>
  </>;
}
