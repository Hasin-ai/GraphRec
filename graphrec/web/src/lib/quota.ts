import type { Tone } from "./status";

/** Shared by summaries, detailed rows, meters and mutation eligibility. */
export function quotaState(used: number, limit: number | null): { status: "informational" | "healthy" | "approaching" | "exhausted"; label: string; tone: Tone; remaining: number | null; ratio: number | null } {
  if (limit === null) return { status: "informational", label: "Informational", tone: "info", remaining: null, ratio: null };
  const remaining = Math.max(0, limit - used);
  const ratio = limit > 0 ? used / limit : 1;
  if (used >= limit) return { status: "exhausted", label: "Exhausted", tone: "danger", remaining, ratio };
  if (ratio >= 0.8) return { status: "approaching", label: "Approaching limit", tone: "warn", remaining, ratio };
  return { status: "healthy", label: "Within limit", tone: "ok", remaining, ratio };
}

const NOUN: Record<string, [string, string]> = {
  stored_products: ["Product storage", "Your catalog has reached its product limit, so new products cannot be added."],
  accepted_events: ["Interaction event", "New interaction events will be rejected until the period resets."],
  recommendation_requests: ["Recommendation request", "Recommendation requests may be rejected until the period resets."],
  training_jobs: ["Training job", "New training jobs cannot start until the period resets."],
  training_cpu_seconds: ["Training compute", "Training compute for this period is used up."],
  artifact_storage_bytes: ["Model storage", "Archive old model versions to free space."],
  active_model_versions: ["Model version", "Archive unused versions before training new ones."],
  inference_replicas: ["Serving replica", "Serving capacity cannot be increased further on this plan."],
  replica_runtime_minutes: ["Serving runtime", "Serving runtime for this period is used up."],
};
/** Plain-language headline and consequence for a quota that needs attention. */
export function quotaMessage(type: string, used: number, limit: number | null): { title: string; body: string } {
  const q = quotaState(used, limit);
  const [noun, consequence] = NOUN[type] ?? [type.replace(/_/g, " "), ""];
  const pct = q.ratio !== null ? Math.round(q.ratio * 100) : null;
  if (limit !== null && used > limit) return { title: `${noun} limit exceeded`, body: `${consequence} ${used.toLocaleString()} used against a limit of ${limit.toLocaleString()} (${(used - limit).toLocaleString()} over).`.trim() };
  if (q.status === "exhausted") return { title: `${noun} limit reached`, body: `${consequence} ${used.toLocaleString()} of ${(limit ?? 0).toLocaleString()} used.`.trim() };
  return { title: `${noun} limit almost reached`, body: `${pct}% used (${used.toLocaleString()} of ${(limit ?? 0).toLocaleString()}).` };
}
