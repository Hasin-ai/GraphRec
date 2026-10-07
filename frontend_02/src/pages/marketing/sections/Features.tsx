import type { ReactNode } from "react";
import { Icon, type IconName } from "../../../ui/icons";
import { Section } from "./Section";

const FEATURES: { icon: IconName; title: string; body: ReactNode }[] = [
  { icon: "clock", title: "Time-aware graph models",
    body: <>DGSR learns from the order and timing of interactions, not just co-occurrence. It reads each shopper's history as a sequence, so what they did last shapes what comes next.</> },
  { icon: "database", title: "Your data, your model",
    body: <>Every tenant trains on its own dataset snapshots. Snapshots and model versions are immutable, so any result can be traced back to the data it came from.</> },
  { icon: "layers", title: "Safe model lifecycle",
    body: <>Activate an eligible version, roll back to a retained one, and archive the rest. One version serves at a time, and a retired version can serve again until you archive it.</> },
  { icon: "users", title: "Cold start handled",
    body: <>Anonymous sessions and new shoppers get session-aware results from their recent views. A fallback tier answers when no model is active yet.</> },
  { icon: "sliders", title: "Business rules",
    body: <>Cap how many items come from one category and boost fresh products with a weight and half-life. Each response lists the rules it applied in <code className="mono">applied_rules</code>.</> },
  { icon: "gauge", title: "Observable serving",
    body: <>Track p95 latency, fallback rate and serving capacity. Usage is measured against your plan's quota, so you see a limit coming before you reach it.</> },
];

export function Features() {
  return <Section id="features" kicker="Features" title="Everything a recommender needs, per tenant"
    intro="GraphRec covers the whole loop, from the first catalog sync to measured clicks and conversions, without you running the infrastructure.">
    <ul className="mkt-features">
      {FEATURES.map(f => <li key={f.title} className="mkt-card">
        <span className="mkt-icon"><Icon name={f.icon} size={20} /></span>
        <h3>{f.title}</h3>
        <p>{f.body}</p>
      </li>)}
    </ul>
  </Section>;
}
