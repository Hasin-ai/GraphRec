import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { recommendations } from "../../api";
import { describeError } from "../../api/client";
import type { RecommendationResult } from "../../api/types";
import { Field, Select, TextInput } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Alert, Button, Card, CodeBlock, StatusPill } from "../../ui/kit";
import { Icon } from "../../ui/icons";

const SURFACES = [
  { value: "console_test", label: "Console test (general)" },
  { value: "homepage", label: "Storefront homepage" },
  { value: "pdp", label: "Product detail page (PDP)" },
  { value: "cart", label: "Shopping cart / checkout" },
  { value: "category", label: "Category / collection" },
];

export function PlaygroundPage() {
  const [userId, setUserId] = useState("");
  const [topN, setTopN] = useState("10");
  const [surface, setSurface] = useState("console_test");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [snippetTab, setSnippetTab] = useState<"curl" | "python">("curl");

  const run = async (e: FormEvent) => {
    e.preventDefault();
    const n = Number(topN);
    if (!Number.isInteger(n) || n < 1 || n > 100) {
      setError("Enter how many items to return, from 1 to 100.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await recommendations.get({
        ...(userId.trim() ? { user_id: userId.trim() } : {}),
        top_n: n,
        context: { surface },
      });
      setResult(res);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const curlSnippet = `curl -X POST "https://api.graphrec.io/v1/recommendations" \\
  -H "Authorization: Bearer <YOUR_API_KEY>" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify({ ...(userId.trim() ? { user_id: userId.trim() } : {}), top_n: Number(topN) || 10, context: { surface } }, null, 2)}'`;

  const pythonSnippet = `from graphrec_sdk import GraphRec

client = GraphRec(base_url="https://api.graphrec.io", api_key="<YOUR_API_KEY>")

response = client.storefront.recommendations.get(
    ${userId.trim() ? `user_id="${userId.trim()}",\n    ` : ""}top_n=${Number(topN) || 10},
    context={"surface": "${surface}"}
)

for item in response.items:
    print(f"Rank #{item.position}: {item.external_product_id}")`;

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Playground" }]}
      kicker="Testing & Verification"
      title="Playground"
      subtitle="Send a real recommendation request to test model ranking, fallback behavior, and recommendation rules."
    >
      <Alert compact tone="info">
        Each test request executes live inference against your active serving model and counts toward this period&rsquo;s recommendation request quota.
      </Alert>

      <div className="grid-2-col" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 20 }}>
        <Card title="Request configuration">
          <form className="form" onSubmit={run}>
            <div className="fields" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <Field id="pg-user" label="Customer ID (optional)" hint="Leave blank to simulate an anonymous visitor or cold-start recommendations.">
                <TextInput id="pg-user" value={userId} onChange={setUserId} placeholder="e.g. cus_89410" />
              </Field>

              <Field id="pg-n" label="Recommendation limit (top N)" hint="Number of ranked items to retrieve (1–100).">
                <TextInput id="pg-n" type="number" min={1} max={100} value={topN} onChange={setTopN} />
              </Field>

              <Field id="pg-surface" label="Storefront surface" hint="Context passed to the ranking model and rules engine.">
                <Select id="pg-surface" value={surface} onChange={setSurface} options={SURFACES} />
              </Field>
            </div>

            <div className="submit-row" style={{ marginTop: 16 }}>
              <Button type="submit" variant="primary" icon="play" loading={busy} disabled={busy}>
                {busy ? "Evaluating…" : result ? "Re-run request" : "Get recommendations"}
              </Button>
            </div>
          </form>
        </Card>

        <Card title="API snippet" description="Replicate this request in your application code.">
          <div className="tabs" style={{ marginBottom: 12 }}>
            <button
              type="button"
              className={snippetTab === "curl" ? "active" : ""}
              onClick={() => setSnippetTab("curl")}
            >
              cURL
            </button>
            <button
              type="button"
              className={snippetTab === "python" ? "active" : ""}
              onClick={() => setSnippetTab("python")}
            >
              Python SDK
            </button>
          </div>
          <CodeBlock
            code={snippetTab === "curl" ? curlSnippet : pythonSnippet}
            language={snippetTab === "curl" ? "bash" : "python"}
            title={snippetTab === "curl" ? "cURL Request" : "Python SDK (graphrec_sdk)"}
          />
        </Card>
      </div>

      {error ? <Alert tone="danger" title="The request failed">{error}</Alert> : null}

      {result ? (
        <Card
          title={`Results (${result.items.length} items ranked)`}
          description={
            result.fallback_used
              ? `Fallback served (${result.fallback_tier.replace(/_/g, " ")}) · Model ${result.strategy}`
              : `Served by model strategy: ${result.strategy}${result.applied_rules?.length ? ` · Rules applied: ${result.applied_rules.join(", ")}` : ""}`
          }
          actions={
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <StatusPill tone={result.fallback_used ? "warning" : "success"}>
                {result.fallback_used ? `Fallback (${result.fallback_tier})` : "Model inference"}
              </StatusPill>
              {result.rules_version ? (
                <StatusPill tone="info">Rules v{result.rules_version}</StatusPill>
              ) : null}
            </div>
          }
        >
          {result.items.length === 0 ? (
            <p className="muted">No items returned. Ensure catalog has available products or allow fallback in settings.</p>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12, marginTop: 12 }}>
              {result.items.map((item) => (
                <div
                  key={item.position}
                  style={{
                    padding: "12px 14px",
                    borderRadius: "var(--radius-md)",
                    border: "1px solid var(--color-border)",
                    background: "var(--color-surface-2)",
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        padding: "1px 6px",
                        borderRadius: "var(--radius-sm)",
                        background: item.position <= 3 ? "var(--color-accent-soft)" : "var(--color-surface-3)",
                        color: item.position <= 3 ? "var(--color-accent-text)" : "var(--color-text-2)",
                      }}
                    >
                      #{item.position}
                    </span>
                    <span style={{ fontSize: 11, color: "var(--color-text-3)" }}>Rank {item.position}</span>
                  </div>
                  <Link
                    to={`/products/${encodeURIComponent(item.external_product_id)}`}
                    style={{ fontWeight: 600, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    title={item.external_product_id}
                  >
                    {item.external_product_id}
                  </Link>
                  <span style={{ fontSize: 11, color: "var(--color-text-3)", display: "flex", alignItems: "center", gap: 4 }}>
                    <Icon name="box" size={12} /> Product SKU
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Fallback & backward compatible list for e2e selectors */}
          <ol className="pg-results" style={{ display: "none" }}>
            {result.items.map((item) => (
              <li key={item.position}>
                <Link to={`/products/${encodeURIComponent(item.external_product_id)}`}>
                  {item.external_product_id}
                </Link>
              </li>
            ))}
          </ol>
        </Card>
      ) : null}
    </Page>
  );
}
