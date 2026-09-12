import { useState } from "react";
import { billing } from "../../api";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDateTime, fmtNumber, fmtQuantity } from "../../lib/format";
import { Page } from "../../ui/Page";
import { Cell, DataTable, DefinitionList, ErrorBanner, FilterBar, Footnote, Panel, PanelTable, Skeleton, Tag } from "../../ui/primitives";

const RESET: Record<string, string> = {
  accepted_events: "monthly",
  recommendation_requests: "monthly",
  training_jobs: "monthly",
  training_cpu_seconds: "monthly",
  stored_products: "no reset · standing limit",
  artifact_storage_bytes: "no reset · standing limit",
  active_model_versions: "no reset · standing limit",
  inference_replicas: "continuous",
  replica_runtime_minutes: "monthly",
};

export function UsagePage() {
  const { can } = useSession();
  const usage = useResource(() => billing.usage(), []);
  const subscription = useResource(() => (can("billing:read") ? billing.subscription() : Promise.resolve(null)), [can("billing:read")]);
  const [type, setType] = useState("all usage types");
  const dims = usage.data?.dimensions ?? [];
  const list = dims.filter((d) => type === "all usage types" || d.type === type);

  const rows = list.map((d) => {
    const informational = d.limit === null;
    return (
      <tr key={d.type}>
        <Cell mono>{d.type}</Cell>
        <Cell mono align="right">
          {fmtQuantity(d.used, d.unit)}
        </Cell>
        <Cell mono align="right">
          {informational ? "—" : fmtQuantity(d.limit ?? 0, d.unit)}
        </Cell>
        <Cell mono align="right">
          {informational || d.remaining === null ? "not applicable" : fmtQuantity(d.remaining, d.unit)}
        </Cell>
        <Cell muted>{RESET[d.type] ?? "monthly"}</Cell>
        <td>
          <Tag tone={informational ? "info" : d.remaining === 0 ? "warn" : "ok"}>{informational ? "informational" : d.remaining === 0 ? "exhausted" : "measured"}</Tag>
        </td>
      </tr>
    );
  });

  const plan = subscription.data;
  return (
    <Page crumbs={[{ label: "Home", to: "/home" }, { label: "Usage & Quotas" }]} kicker={plan ? `Plan ${plan.plan_code}` : "Usage"} title="Usage & Quotas" subtitle="Measured quantity against the effective limit for each usage type. A dimension without a limit is stated as informational and never shown as zero remaining.">
      {usage.error ? <ErrorBanner error={usage.error} /> : null}
      {usage.data ? (
        <DefinitionList
          items={[
            { label: "Period", value: `${fmtDateTime(usage.data.period_start)} → ${fmtDateTime(usage.data.period_end)}`, mono: true },
            { label: "Resets at", value: fmtDateTime(usage.data.reset_at), mono: true },
            { label: "Last reconciled", value: fmtDateTime(usage.data.last_reconciled_at), mono: true },
            { label: "Limits source", badge: <Tag tone={usage.data.project_defaults ? "warn" : "ok"}>{usage.data.project_defaults ? "project defaults" : "assigned plan"}</Tag> },
          ]}
        />
      ) : null}
      <FilterBar filters={[{ id: "type", label: "Usage type", value: type, onChange: setType, options: ["all usage types", ...dims.map((d) => d.type)] }]} onClear={() => setType("all usage types")} />
      {usage.loading && !usage.data ? (
        <Skeleton />
      ) : (
        <DataTable minWidth={1000} columns={["Usage type", { label: "Measured", align: "right" }, { label: "Effective limit", align: "right" }, { label: "Remaining", align: "right" }, "Reset period", "Measurement"]} rows={rows} count={`${list.length} of ${dims.length}`} empty={{ title: "No usage types match this filter", body: "Clear the filter to see all nine usage types." }} />
      )}
      {plan ? (
        <Panel title="Subscription" badge={<Tag tone={plan.status === "active" ? "ok" : "warn"}>{plan.status}</Tag>} note={plan.project_defaults ? "project defaults" : "assigned plan"} body="Plan limits become the effective quota unless a platform-approved override applies.">
          <PanelTable
            columns={["Limit", { label: "Value", align: "right" }]}
            rows={Object.entries(plan.limits).map(([k, v]) => (
              <tr key={k}>
                <Cell mono>{k}</Cell>
                <Cell mono align="right">
                  {fmtNumber(v)}
                </Cell>
              </tr>
            ))}
          />
        </Panel>
      ) : subscription.error ? (
        <ErrorBanner error={subscription.error} title="The subscription could not be read" />
      ) : null}
      <Footnote>Usage is reconciled from an immutable ledger; reads of this page are rate-limited per credential.</Footnote>
    </Page>
  );
}
