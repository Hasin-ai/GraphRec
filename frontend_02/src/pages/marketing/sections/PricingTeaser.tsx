import { Link } from "react-router-dom";
import { HEADLINE_LIMITS, formatLimit, limitLabel, MONTHLY_LIMITS } from "../../../marketing/plans";
import { useLivePlans } from "../../../marketing/useLivePlans";
import { Section } from "./Section";

export function PricingTeaser() {
  const { plans } = useLivePlans();
  return <Section id="plans" kicker="Plans" title="Plans differ by capacity, not features"
    intro="Every tenant gets the whole platform. Plans set how much of it you can use.">
    <ul className="mkt-plans">
      {plans.map(plan => <li key={plan.code} className="mkt-card mkt-plan">
        <h3>{plan.name}</h3>
        <p className="mkt-plan-tagline">{plan.tagline}</p>
        <dl className="mkt-limits">
          {HEADLINE_LIMITS.map(key => <div key={key}>
            <dt>{limitLabel(key)}{MONTHLY_LIMITS.has(key) ? " / month" : ""}</dt>
            <dd className="mono">{formatLimit(key, plan.limits[key])}</dd>
          </div>)}
        </dl>
      </li>)}
    </ul>
    <p className="mkt-more"><Link to="/pricing">Compare every limit</Link></p>
  </Section>;
}
