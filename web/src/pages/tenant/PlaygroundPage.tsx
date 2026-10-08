import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { recommendations } from "../../api";
import { describeError } from "../../api/client";
import type { RecommendationResult } from "../../api/types";
import { Field, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Alert, Button, Card } from "../../ui/kit";

/** Playground: the "Try a recommendation" flow from Overview, as its own page. Same API call. */
export function PlaygroundPage() {
  const [userId, setUserId] = useState("");
  const [topN, setTopN] = useState("10");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const run = async (e: FormEvent) => {
    e.preventDefault();
    const n = Number(topN);
    if (!Number.isInteger(n) || n < 1 || n > 100) { setError("Enter how many items to return, from 1 to 100."); return; }
    setBusy(true); setError(null);
    try { setResult(await recommendations.get({ ...(userId.trim() ? { user_id: userId.trim() } : {}), top_n: n, context: { surface: "console_test" } })); }
    catch (err) { setError(describeError(err)); }
    finally { setBusy(false); }
  };
  return <Page title="Playground" subtitle="Send a real recommendation request and inspect what your storefront would receive.">
    <Alert compact tone="info">Each request counts toward this period's recommendation-request quota.</Alert>
    <Card title="Request">
      <form className="form" onSubmit={run}>
        <div className="fields">
          <Field id="pg-user" label="Customer ID (optional)" hint="Leave empty to see what an anonymous visitor gets.">
            <TextInput id="pg-user" value={userId} onChange={setUserId} placeholder="e.g. 10423" />
          </Field>
          <Field id="pg-n" label="Number of items">
            <TextInput id="pg-n" type="number" min={1} max={100} value={topN} onChange={setTopN} />
          </Field>
        </div>
        <div className="submit-row"><Button type="submit" variant="primary" icon="play" loading={busy} disabled={busy}>{busy ? "Requesting…" : result ? "Run again" : "Get recommendations"}</Button></div>
      </form>
    </Card>
    {error ? <Alert tone="danger" title="The request failed">{error}</Alert> : null}
    {result ? <Card title={`${result.items.length} items`} description={result.fallback_used ? `Fallback (${result.fallback_tier.replace(/_/g, " ")})` : `Model ${result.strategy.replace(/_/g, " ")}${result.applied_rules.length ? ` · rules: ${result.applied_rules.join(", ")}` : ""}`}>
      <ol className="pg-results">{result.items.map(item => <li key={item.position}><Link to={`/products/${encodeURIComponent(item.external_product_id)}`}>{item.external_product_id}</Link></li>)}</ol>
    </Card> : null}
  </Page>;
}
