import { serving } from "../../api";
import { useResource } from "../../hooks/useResource";
import { fmtDateTime, fmtNumber, humanize } from "../../lib/format";
import { Cell, DataTable, DefinitionList, ErrorBanner, Panel, Skeleton } from "../../ui/primitives";

/** XR-F-08: capacity policy, live demand and scaling events. */
export function ScalingPanel() {
  const scaling = useResource(() => serving.scaling(), []);
  const s = scaling.data && Array.isArray(scaling.data.events) ? scaling.data : null;
  const fixed = s ? s.min_capacity === s.max_capacity : false;
  return <Panel title="Serving capacity" note={s ? (fixed ? "Fixed size" : "Scales with demand") : undefined}>
    {scaling.error ? <ErrorBanner error={scaling.error} title="Capacity unavailable" onRetry={scaling.reload} /> : null}
    {!s ? (scaling.loading ? <Skeleton rows={2} /> : null) : <>
      <DefinitionList items={[
        { label: "Capacity", value: s.managed ? `${s.ready_capacity} of ${s.desired_capacity} ready${fixed ? ` (fixed at ${s.max_capacity})` : ` (scales ${s.min_capacity}–${s.max_capacity})`}` : "Not managed: activate a model version" },
        { label: "Concurrent requests", value: s.serving_slots === null ? "No limit" : `Up to ${fmtNumber(s.serving_slots)} at once` },
        { label: "Demand", value: `${fmtNumber(s.measured_rpm)} req/min now · peak ${fmtNumber(s.peak_rpm)}` },
        ...(fixed ? [] : [{ label: "Scaling rule", value: `1 unit per ${fmtNumber(s.target_rpm_per_replica)} req/min; scales down after ${Math.round(s.scale_down_stabilization_seconds / 60)} min of lower demand` }]),
        { label: "Last change", value: s.last_scaled_at ? fmtDateTime(s.last_scaled_at) : "No changes yet" },
      ]} />
      {s.events.length ? <DataTable minWidth={720} columns={["When", "Change", "Reason", { label: "Req/min", align: "right" }, { label: "Peak", align: "right" }]}
        rows={s.events.map(e => <tr key={e.id}><Cell>{fmtDateTime(e.occurred_at)}</Cell><Cell>{e.from_capacity} → {e.to_capacity}</Cell><Cell>{humanize(e.reason)}</Cell><Cell align="right">{fmtNumber(e.measured_rpm)}</Cell><Cell align="right">{fmtNumber(e.peak_rpm)}</Cell></tr>)}
        count={`${s.events.length} recent scaling ${s.events.length === 1 ? "change" : "changes"}`} /> : null}
      <details className="details-section"><summary>How serving capacity works here</summary><p className="footnote">{s.limitation}</p></details>
    </>}
  </Panel>;
}
