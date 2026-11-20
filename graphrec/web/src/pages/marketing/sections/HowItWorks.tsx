import { Section } from "./Section";

const STEPS: { title: string; body: string; endpoints: string[] }[] = [
  { title: "Sync catalog", body: "Send products in bulk, keyed by your own product IDs.", endpoints: ["POST /v1/products:bulk-upsert"] },
  { title: "Stream events", body: "Views, clicks, add-to-cart, purchases and ratings, in batches of up to 1,000.", endpoints: ["POST /v1/events/batches"] },
  { title: "Snapshot & train", body: "Freeze an immutable snapshot of your history and train a DGSR model on it.", endpoints: ["POST /v1/datasets/snapshots", "POST /v1/training-jobs"] },
  { title: "Activate a version", body: "Promote an evaluated version to serving, or roll back to a retained one.", endpoints: ["POST /v1/model-versions/{id}:activate"] },
  { title: "Serve & measure feedback", body: "Request Top-N results, then report impressions, clicks and conversions.", endpoints: ["POST /v1/recommendations", "POST /v1/feedback/{type}"] },
];

export function HowItWorks() {
  return <Section id="how-it-works" tone="alt" kicker="How it works" title="Five steps from catalog to measured results"
    intro="Each step maps to an API endpoint and to a page in the console, so you can script it or click through it.">
    <ol className="mkt-steps">
      {STEPS.map(step => <li key={step.title}>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        <div className="mkt-endpoints" aria-label="API endpoints">{step.endpoints.map(e => <code key={e} className="mkt-endpoint mono">{e}</code>)}</div>
      </li>)}
    </ol>
  </Section>;
}
