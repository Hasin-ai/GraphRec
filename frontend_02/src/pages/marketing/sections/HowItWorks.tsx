import { Section } from "./Section";

const STEPS: { title: string; body: string; endpoint: string }[] = [
  { title: "Sync catalog", body: "Send products in bulk, keyed by your own product IDs.", endpoint: "POST /v1/products:bulk-upsert" },
  { title: "Stream events", body: "Views, clicks, add-to-cart, purchases and ratings, in batches of up to 1,000.", endpoint: "POST /v1/events" },
  { title: "Snapshot & train", body: "Freeze an immutable snapshot of your history and train a DGSR model on it.", endpoint: "POST /v1/datasets/snapshots · POST /v1/training-jobs" },
  { title: "Activate a version", body: "Promote an evaluated version to serving, or roll back to a retained one.", endpoint: "POST /v1/model-versions/{id}:activate" },
  { title: "Serve & measure feedback", body: "Request Top-N results, then report impressions, clicks and conversions.", endpoint: "POST /v1/recommendations · /v1/feedback/impressions|clicks|conversions" },
];

export function HowItWorks() {
  return <Section id="how-it-works" tone="alt" kicker="How it works" title="Five steps from catalog to measured results"
    intro="Each step maps to an API endpoint and to a page in the console, so you can script it or click through it.">
    <ol className="mkt-steps">
      {STEPS.map(step => <li key={step.title}>
        <h3>{step.title}</h3>
        <p>{step.body}</p>
        <span className="mkt-endpoint mono">{step.endpoint}</span>
      </li>)}
    </ol>
  </Section>;
}
