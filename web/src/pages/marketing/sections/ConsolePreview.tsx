import { BrandMark } from "../../../brand/BrandMark";
import { Icon, type IconName } from "../../../ui/icons";
import { Section } from "./Section";

const NAV: { label: string; items: [IconName, string][] }[] = [
  { label: "", items: [["home", "Overview"]] },
  { label: "Data", items: [["box", "Products"], ["refresh-cw", "Catalog sync"], ["activity", "Events"], ["database", "Datasets"]] },
  { label: "Models", items: [["cpu", "Training"], ["layers", "Model Versions"]] },
  { label: "Monitoring", items: [["server", "Service Status"], ["gauge", "Usage & Quotas"]] },
];
const HEALTH: [tone: string, label: string, word: string, detail: string][] = [
  ["success", "Serving", "Available", "1 replica"],
  ["success", "Model", "DGSR model · v3", "Active"],
  ["success", "Events", "Flowing", "Last batch 2 min ago"],
  ["warning", "Quota", "Near limit", "Recommendation requests"],
];
const METRICS: [label: string, value: string, note: string][] = [
  ["Requests", "12,480", "Last 24 hours"],
  ["p95 latency", "184 ms", "Last 24 hours"],
  ["Fallback rate", "2.1%", "Last 24 hours"],
  ["Accepted events", "41,902", "This month"],
];

/**
 * A static, non-interactive mock of the tenant Overview, built from the console's
 * own classes so it follows theme changes. Hidden from assistive technology; the
 * caption below describes it.
 */
export function ConsolePreview() {
  return <Section id="console" kicker="The console" title="See what your recommender is doing"
    intro="Administrators and developers share one console: catalog, events, training, model versions, rules, serving status and usage.">
    <figure className="mkt-preview">
      <div className="mkt-preview-frame" aria-hidden="true">
        <div className="mkt-pv-side">
          <div className="mkt-pv-brand"><BrandMark />GraphRec</div>
          {NAV.map(group => <div key={group.label || "top"} className="mkt-pv-group">
            {group.label ? <div className="mkt-pv-label">{group.label}</div> : null}
            {group.items.map(([icon, label]) => <div key={label} className={`mkt-pv-item${label === "Overview" ? " is-active" : ""}`}><Icon name={icon} size={15} />{label}</div>)}
          </div>)}
        </div>
        <div className="mkt-pv-main">
          <div className="mkt-pv-title">Overview</div>
          <div className="health-card">
            <div className="hc-head"><span className="mkt-pv-h">System health</span><span className="hc-sum tone-warn">1 warning</span></div>
            <div className="hl-grid">{HEALTH.map(([tone, label, word, detail]) => <div key={label} className="hl-row">
              <span className="hl-label"><span className={`status-dot tone-${tone}`}><span className="sd" /></span>{label}</span>
              <span className="hl-word">{word}</span><span className="hl-detail">{detail}</span>
            </div>)}</div>
          </div>
          <div className="kpi-strip">{METRICS.map(([label, value, note]) => <div key={label} className="kpi-cell">
            <span className="kpi-label">{label}</span><span className="kpi-num">{value}</span><span className="kpi-note">{note}</span>
          </div>)}</div>
        </div>
      </div>
      <figcaption>The tenant Overview: service health, the serving model, traffic and quota at a glance. Sample values, not measurements.</figcaption>
    </figure>
  </Section>;
}
