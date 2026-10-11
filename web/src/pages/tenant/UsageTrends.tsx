import { useMemo, useState } from "react";
import { billing } from "../../api";
import type { TrendGranularity, UsageTrend } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { fmtNumber, humanize } from "../../lib/format";
import { Field, Select, TextInput } from "../../ui/Form";
import { Banner, Cell, DataTable, ErrorBanner, Panel, Skeleton } from "../../ui/primitives";

const TYPES = ["accepted_events", "recommendation_requests", "training_jobs", "training_cpu_seconds", "artifact_storage_bytes"];
const DEFAULT_DAYS: Record<TrendGranularity, number> = { hour: 2, day: 30, week: 84 };
const MAX_DAYS: Record<TrendGranularity, number> = { hour: 31, day: 366, week: 728 };
const isoDay = (d: Date) => d.toISOString().slice(0, 10);

/** Validates a [from, to] day range for a granularity; returns an error message or null. */
export function rangeError(from: string, to: string, granularity: TrendGranularity): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) return "Enter dates as YYYY-MM-DD.";
  const start = Date.parse(`${from}T00:00:00Z`), end = Date.parse(`${to}T00:00:00Z`) + 86_400_000;
  if (Number.isNaN(start) || Number.isNaN(end)) return "Enter valid dates.";
  if (end <= start) return "The end date must be on or after the start date.";
  if ((end - start) / 86_400_000 > MAX_DAYS[granularity]) return `${humanize(granularity)} trends can cover at most ${MAX_DAYS[granularity]} days.`;
  return null;
}

function Bars({ trend, type }: { trend: UsageTrend; type: string }) {
  const values = trend.buckets.map(b => b.values[type] ?? 0);
  const max = Math.max(1, ...values);
  const w = 640, h = 140, gap = values.length > 60 ? 0 : 1, bw = Math.max(1, w / Math.max(values.length, 1) - gap);
  return <svg role="img" aria-label={`${humanize(type)} per ${trend.granularity}`} viewBox={`0 0 ${w} ${h + 16}`} className="trend-chart" style={{ width: "100%", maxWidth: w }}>
    <line x1={0} y1={h} x2={w} y2={h} stroke="currentColor" strokeOpacity={0.25} />
    {values.map((v, i) => { const bh = (v / max) * (h - 4); return <rect key={trend.buckets[i].start} x={i * (bw + gap)} y={h - bh} width={bw} height={bh} fill="currentColor" fillOpacity={0.7}><title>{`${trend.buckets[i].start}: ${fmtNumber(v)}`}</title></rect>; })}
    <text x={0} y={h + 13} fontSize={10} fill="currentColor" fillOpacity={0.6}>{trend.buckets[0]?.start.slice(0, 16).replace("T", " ")}</text>
    <text x={w} y={h + 13} fontSize={10} textAnchor="end" fill="currentColor" fillOpacity={0.6}>max {fmtNumber(max)}</text>
  </svg>;
}

/** XR-F-07: usage over time from the usage ledger. */
export function UsageTrends() {
  const [granularity, setGranularity] = useState<TrendGranularity>("day");
  const [type, setType] = useState(TYPES[0]);
  const [from, setFrom] = useState(() => isoDay(new Date(Date.now() - DEFAULT_DAYS.day * 86_400_000)));
  const [to, setTo] = useState(() => isoDay(new Date()));
  const error = rangeError(from, to, granularity);
  const query = useMemo(() => error ? null : { granularity, start: `${from}T00:00:00Z`, end: new Date(Date.parse(`${to}T00:00:00Z`) + 86_400_000).toISOString(), types: TYPES }, [granularity, from, to, error]);
  const trend = useResource(() => query ? billing.trends(query) : Promise.resolve(null), [JSON.stringify(query)]);
  const data = trend.data && Array.isArray(trend.data.buckets) ? trend.data : null;
  const total = data ? data.totals[type] ?? 0 : 0;
  return <Panel title="Usage trends" note="Totals per period, in UTC">
    <div className="fields trend-controls">
      <Field id="ut-gran" label="Granularity"><Select id="ut-gran" value={granularity} onChange={v => { const g = v as TrendGranularity; setGranularity(g); setFrom(isoDay(new Date(Date.now() - DEFAULT_DAYS[g] * 86_400_000))); setTo(isoDay(new Date())); }} options={[{ value: "hour", label: "Hourly" }, { value: "day", label: "Daily" }, { value: "week", label: "Weekly" }]} /></Field>
      <Field id="ut-type" label="Usage type"><Select id="ut-type" value={type} onChange={setType} options={TYPES.map(t => ({ value: t, label: humanize(t) }))} /></Field>
      <Field id="ut-from" label="From (UTC date)" error={error ?? undefined}><TextInput id="ut-from" value={from} onChange={setFrom} mono placeholder="YYYY-MM-DD" /></Field>
      <Field id="ut-to" label="To (UTC date, inclusive)"><TextInput id="ut-to" value={to} onChange={setTo} mono placeholder="YYYY-MM-DD" /></Field>
    </div>
    {trend.error ? <ErrorBanner error={trend.error} title="Trend unavailable" onRetry={trend.reload} /> : null}
    {!data && trend.loading && query ? <Skeleton rows={3} /> : null}
    {data ? <>
      <p className="footnote">{humanize(type)}: {fmtNumber(total)} in {data.buckets.length} {data.granularity} buckets.</p>
      {total === 0 ? <Banner tone="info" title="No usage in this range">Choose another range or usage type. Empty periods are shown as zero.</Banner> : <Bars trend={data} type={type} />}
      <details className="details-section"><summary>Values by period</summary>
        <DataTable minWidth={420} columns={["Period start (UTC)", { label: humanize(type), align: "right" }]}
          rows={data.buckets.filter(b => (b.values[type] ?? 0) > 0).map(b => <tr key={b.start}><Cell mono>{b.start.slice(0, 16).replace("T", " ")}</Cell><Cell mono align="right">{fmtNumber(b.values[type] ?? 0)}</Cell></tr>)}
          count={`${data.buckets.filter(b => (b.values[type] ?? 0) > 0).length} non-empty periods`} empty={{ title: "No non-empty periods", body: "Every period in this range is zero." }} />
      </details>
    </> : null}
  </Panel>;
}
