import { Link } from "react-router-dom";
import { models, serving } from "../../api";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDateTime, fmtPercent, relativeSeconds, shortId } from "../../lib/format";
import { Page } from "../../ui/Page";
import { Badge, Cell, DefinitionList, ErrorBanner, Footnote, Panel, PanelTable, Skeleton, Stats, Tag } from "../../ui/primitives";

export function ServiceStatusPage() {
  const { can } = useSession();
  const deployment = useResource(() => serving.deployment(), []);
  const replicas = useResource(() => serving.replicas(), []);
  const autoscaling = useResource(() => serving.autoscaling(), []);
  const metrics = useResource(() => (can("metrics:read") ? serving.metrics() : Promise.resolve(null)), [can("metrics:read")]);
  const versions = useResource(() => (can("models:read") ? models.list() : Promise.resolve(null)), [can("models:read")]);

  const d = deployment.data;
  const m = metrics.data;
  const active = versions.data?.items.find((v) => v.status === "active");
  const activeLabel = d?.active_model_version_id ? (active ? active.version_tag : shortId(d.active_model_version_id)) : "none";

  function reload() {
    void deployment.reload();
    void replicas.reload();
    void autoscaling.reload();
    void metrics.reload();
  }

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Service Status" }]}
      kicker="Serving"
      title="Service Status"
      badge={d ? <Badge group="deploy" value={d.status} /> : undefined}
      subtitle="Recommendation traffic is served server-to-server. This board reports availability and capacity; recommendation results themselves are never shown in this console."
      updated={deployment.loadedAt ? `updated ${relativeSeconds(deployment.loadedAt)}` : undefined}
      actions={[{ label: "Refresh", onClick: reload }]}
    >
      {deployment.error ? <ErrorBanner error={deployment.error} /> : null}
      {!d && deployment.loading ? (
        <Skeleton />
      ) : d ? (
        <>
          <Stats
            items={[
              { label: "Deployment", value: d.status, note: d.failure_reason ?? "no failure recorded" },
              { label: "Active version", value: activeLabel, note: d.active_model_version_id ? `since ${fmtDateTime(d.last_transition_at)}` : "no version serving" },
              { label: "Desired capacity", value: String(d.desired_replicas), note: "replicas requested" },
              { label: "Ready capacity", value: String(d.ready_replicas), note: d.ready_replicas < d.desired_replicas ? "below desired" : "matches desired", tone: d.ready_replicas < d.desired_replicas ? "warn" : undefined },
              { label: "Fallback rate", value: m ? fmtPercent(m.fallback_rate) : metrics.loading ? "…" : "n/a", note: m ? "requests served by fallback" : "metrics:read not held" },
              { label: "Latency p95", value: m ? `${m.p95_latency_ms} ms` : metrics.loading ? "…" : "n/a", note: m ? `${m.request_rate.toFixed(1)} req/s · error rate ${fmtPercent(m.error_rate)}` : "" },
            ]}
          />
          <DefinitionList
            items={[
              { label: "Deployment state", badge: <Badge group="deploy" value={d.status} /> },
              { label: "Last transition", value: fmtDateTime(d.last_transition_at), mono: true },
              { label: "Desired version", value: d.desired_model_version_id ? (active && active.id === d.desired_model_version_id ? <Link to={`/models/${active.id}`}>{active.version_tag}</Link> : shortId(d.desired_model_version_id)) : "none", mono: true },
              { label: "Measurement window", value: m ? `${fmtDateTime(m.window_start)} → ${fmtDateTime(m.window_end)}` : "—", mono: true },
            ]}
          />
        </>
      ) : null}
      <div className="panels">
        <Panel title="Replicas" note={replicas.data ? `${replicas.data.ready_replicas} / ${replicas.data.desired_replicas} ready` : undefined} body="Each replica serves the active version. A replica without a version is idle.">
          {replicas.error ? <ErrorBanner error={replicas.error} /> : null}
          {replicas.data ? (
            <PanelTable
              columns={["Replica", "Status", "Ready", "Version", "Started"]}
              rows={replicas.data.replicas.map((r) => (
                <tr key={r.id}>
                  <Cell mono>{r.id}</Cell>
                  <td>
                    <Badge group="replica" value={r.status} />
                  </td>
                  <td>
                    <Tag tone={r.ready ? "ok" : "neu"}>{r.ready ? "yes" : "no"}</Tag>
                  </td>
                  <Cell mono>{r.model_version_id ? shortId(r.model_version_id) : "—"}</Cell>
                  <Cell mono>{fmtDateTime(r.started_at)}</Cell>
                </tr>
              ))}
            />
          ) : null}
        </Panel>
        <Panel
          title="Autoscaling"
          badge={autoscaling.data ? <Tag tone={autoscaling.data.capacity_blocked ? "warn" : "ok"}>{autoscaling.data.capacity_blocked ? "capacity blocked" : "nominal"}</Tag> : undefined}
          dl={
            autoscaling.data
              ? [
                  { label: "Replica range", value: `${autoscaling.data.min_replicas} – ${autoscaling.data.max_replicas}`, mono: true },
                  { label: "CPU target", value: `${autoscaling.data.cpu_target_percent}%`, mono: true },
                  { label: "Desired / ready", value: `${autoscaling.data.desired_replicas} / ${autoscaling.data.ready_replicas}`, mono: true },
                  { label: "Metrics available", value: autoscaling.data.metrics_available ? "yes" : "no: measurement gap", mono: true },
                ]
              : []
          }
        >
          {autoscaling.error ? <ErrorBanner error={autoscaling.error} /> : null}
          {autoscaling.data?.recent_actions.length ? (
            <PanelTable
              columns={["Occurred at", "From", "To", "Reason"]}
              rows={autoscaling.data.recent_actions.map((a, i) => (
                <tr key={i}>
                  <Cell mono>{fmtDateTime(a.occurred_at)}</Cell>
                  <Cell mono>{a.from_replicas}</Cell>
                  <Cell mono>{a.to_replicas}</Cell>
                  <Cell muted>{a.reason}</Cell>
                </tr>
              ))}
            />
          ) : null}
        </Panel>
        {m?.quality ? (
          <Panel
            title="Serving quality"
            note={`recorded ${fmtDateTime(m.quality.recorded_at)}`}
            body="Offline and online quality signals for the active version."
            dl={[
              { label: "Hit@10", value: m.quality.hit_at_10.toFixed(3), mono: true },
              { label: "NDCG@10", value: m.quality.ndcg_at_10.toFixed(3), mono: true },
              { label: "Retrieval recall@k", value: m.quality.retrieval_recall_at_k.toFixed(3), mono: true },
              { label: "Catalog coverage", value: m.quality.catalog_coverage.toFixed(2), mono: true },
              { label: "Intra-list diversity", value: m.quality.intra_list_diversity.toFixed(2), mono: true },
              { label: "Training / validation loss", value: `${m.quality.training_loss.toFixed(3)} / ${m.quality.validation_loss.toFixed(3)}`, mono: true },
            ]}
          />
        ) : null}
      </div>
      <Footnote>Deployment, autoscaling and metric readings are placeholders in this release of the API and are rendered as returned.</Footnote>
    </Page>
  );
}
