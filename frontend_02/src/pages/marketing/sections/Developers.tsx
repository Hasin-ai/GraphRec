import { useRef, useState, type KeyboardEvent } from "react";
import { Icon } from "../../../ui/icons";
import { CopyButton } from "../../../ui/primitives";
import { Section } from "./Section";

const PYTHON = `from graphrec_sdk import GraphRec
from graphrec_sdk.ecommerce import CatalogSync, EventTracker

client = GraphRec(base_url="https://graphrec.example.com", api_key="gr_live_...")

CatalogSync(client).run([{"external_id": "sku-100", "title": "Linen shirt", "price": "49.90", "category": "shirts"}])

with EventTracker(client, batch_size=100, flush_interval=5) as tracker:
    tracker.view("customer-42", "sku-100", session_id="sess-1")
    tracker.purchase("customer-42", "sku-100", order_id="ORD-1001")

recs = client.storefront.recommendations.get(user_id="customer-42", top_n=10)`;

const HTTP = `POST /v1/recommendations HTTP/1.1
Host: graphrec.example.com
Authorization: ApiKey <credential secret>
Content-Type: application/json

{
  "user_id": "cus-9931",
  "top_n": 10,
  "fallback_allowed": true,
  "context": { "surface": "cart" }
}`;

const RESPONSE = `{
  "request_id": "5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5",
  "items": [
    { "external_product_id": "sku-100", "position": 1 },
    { "external_product_id": "sku-214", "position": 2 },
    { "external_product_id": "sku-087", "position": 3 }
  ],
  "model_version_id": "0c6e2a51-93b4-4f7d-8a1e-5d2c7b9f4e10",
  "strategy": "personalized",
  "fallback_used": false,
  "fallback_tier": "none",
  "applied_rules": ["diversity"],
  "rules_version": 3
}`;

const TABS = [
  { id: "python", label: "Python SDK", file: "storefront.py", code: PYTHON },
  { id: "http", label: "HTTP request", file: "POST /v1/recommendations", code: HTTP },
  { id: "response", label: "Response", file: "200 OK · application/json", code: RESPONSE, caption: "Every result says which model and which rules produced it." },
] as const;

/** WAI-ARIA tabs: arrow keys, Home and End move between tabs and activate them. */
function CodeTabs() {
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const select = (index: number) => { setActive(index); refs.current[index]?.focus(); };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const last = TABS.length - 1;
    const next = e.key === "ArrowRight" ? (active === last ? 0 : active + 1)
      : e.key === "ArrowLeft" ? (active === 0 ? last : active - 1)
      : e.key === "Home" ? 0 : e.key === "End" ? last : null;
    if (next === null) return;
    e.preventDefault();
    select(next);
  };
  return <div className="mkt-code">
    <div className="mkt-tabs" role="tablist" aria-label="Code samples" onKeyDown={onKeyDown}>
      {TABS.map((tab, i) => <button key={tab.id} ref={el => { refs.current[i] = el; }} type="button" role="tab" id={`code-tab-${tab.id}`}
        aria-selected={i === active} aria-controls={`code-panel-${tab.id}`} tabIndex={i === active ? 0 : -1} onClick={() => setActive(i)}>{tab.label}</button>)}
    </div>
    {TABS.map((tab, i) => <div key={tab.id} role="tabpanel" id={`code-panel-${tab.id}`} aria-labelledby={`code-tab-${tab.id}`} hidden={i !== active} className="snippet">
      <div className="s-head">
        <span className="s-label">{tab.file}</span>
        <span className="mkt-copy"><CopyButton value={tab.code} /></span>
      </div>
      <pre tabIndex={0} aria-label={`${tab.label} sample`}><code>{tab.code}</code></pre>
      {"caption" in tab ? <p className="mkt-code-caption">{tab.caption}</p> : null}
    </div>)}
  </div>;
}

const POINTS = [
  <>Scoped API keys. A storefront key can send <span className="mono">events:*</span> and read recommendations without ever holding <span className="mono">training:*</span> or <span className="mono">models:*</span>.</>,
  <>Idempotent event batches with duplicate detection. A replayed batch is confirmed, not counted twice.</>,
  <>One error envelope everywhere, with a <span className="mono">correlation_id</span> you can quote to support.</>,
  <>A typed Python SDK, <span className="mono">graphrec-sdk</span>, with sync and async clients.</>,
  <>Bulk calls split automatically to stay under the 16 KiB request body limit.</>,
  <>Retries that never duplicate side effects.</>,
];

export function Developers() {
  return <Section id="developers" kicker="Developers" title="One contract for your storefront and back office"
    intro="Call the REST API directly or use the Python SDK. Both speak the same contract.">
    <div className="mkt-dev">
      <ul className="mkt-checks">
        {POINTS.map((point, i) => <li key={i}><Icon name="check" size={16} /><span>{point}</span></li>)}
      </ul>
      <CodeTabs />
    </div>
  </Section>;
}
