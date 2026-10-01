import { serving } from "../../api";
import { useResource } from "../../hooks/useResource";
import { fmtDateTime, fmtNumber, humanize } from "../../lib/format";
import { Cell, DataTable, DefinitionList, ErrorBanner, Panel, Skeleton } from "../../ui/primitives";

/** XR-F-08: capacity policy, live demand and scaling events. */
export function ScalingPanel() {
  const scaling = useResource(() => serving.scaling(), []);
  const s = scaling.data && Array.isArray(scaling.data.events) ? scaling.data : null;
  return <Panel title="Serving capacity" note="Metrics-driven scaling (XR-F-08)" actions={[{ label: "Refresh capacity", onClick: () => void scaling.reload() }]}>
    {scaling.error ? <ErrorBanner error={scaling.error} title="Capacity unavailable" onRetry={scaling.reload} /> : null}
    {!s ? (scaling.loading ? <Skeleton rows={2} /> : null) : <>
      <DefinitionList items={[
        { label: "Capacity", value: s.managed ? `${s.ready_capacity} ready of ${s.desired_capacity} desired (range ${s.min_capacity}–${s.max_capacity})` : "Not managed — activate a model version", mono: true },
        { label: "Concurrent serving slots", value: s.serving_slots === null ? "No limit" : fmtNumber(s.serving_slots), mono: true },
        { label: "Demand", value: `${fmtNumber(s.measured_rpm)} req/min now · peak ${fmtNumber(s.peak_rpm)} in the last ${Math.max(1, Math.round(s.scale_down_stabilization_seconds / 60))} min`, mono: true },
        { label: "Policy", value: `1 unit per ${fmtNumber(s.target_rpm_per_replica)} req/min; scale up at once, down after ${s.scale_down_stabilization_seconds}s of lower demand` },
        { label: "Last scaled", value: fmtDateTime(s.last_scaled_at) },
      ]} />
      <p className="footnote">{s.limitation}</p>
      <DataTable minWidth={720} columns={["When", "Change", "Reason", { label: "Req/min", align: "right" }, { label: "Peak", align: "right" }]}
        rows={s.events.map(e => <tr key={e.id}><Cell mono>{fmtDateTime(e.occurred_at)}</Cell><Cell mono>{e.from_capacity} → {e.to_capacity}</Cell><Cell>{humanize(e.reason)}</Cell><Cell mono align="right">{fmtNumber(e.measured_rpm)}</Cell><Cell mono align="right">{fmtNumber(e.peak_rpm)}</Cell></tr>)}
        count={`${s.events.length} recent scaling events`} empty={{ title: "No scaling events yet", body: "Capacity changes appear here when demand crosses the policy thresholds." }} />
    </>}
  </Panel>;
}
