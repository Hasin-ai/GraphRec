export type Tone = "ok" | "warn" | "danger" | "info" | "neu";

/**
 * State enumerations and their fixed semantic colours (the prototype's GROUPS map),
 * narrowed to the values the API actually emits.
 */
const GROUPS: Record<string, Record<string, Tone>> = {
  job: { queued: "neu", preparing_data: "info", training: "info", succeeded: "ok", failed: "danger" },
  model: { eligible: "info", active: "ok", retired: "warn", archived: "neu" },
  deploy: { stopped: "neu", pending: "info", progressing: "info", degraded: "warn", available: "ok" },
  tenant: { deleted: "neu", pending: "info", suspended: "warn", deleting: "warn", active: "ok" },
  key: { active: "ok", expired: "warn", revoked: "danger" },
  batch: { completed: "ok", processing: "info", failed: "danger" },
  outcome: { success: "ok", succeeded: "ok", denied: "warn", failure: "danger", failed: "danger" },
  sev: { info: "info", low: "info", warning: "warn", medium: "warn", error: "danger", high: "danger", critical: "danger" },
  platform: { healthy: "ok", degraded: "warn", online: "ok", connected: "ok", unavailable: "danger", not_deployed: "neu" },
  replica: { ready: "ok", idle: "neu" },
};

export function toneFor(group: keyof typeof GROUPS | string, value: string): Tone {
  return GROUPS[group]?.[value] ?? "neu";
}

/** Training pipeline stages shown on the stage rail, in order. */
export const JOB_STAGES = ["queued", "preparing_data", "training", "succeeded"] as const;

export function jobStageIndex(status: string): number {
  const i = JOB_STAGES.indexOf(status as (typeof JOB_STAGES)[number]);
  if (i >= 0) return i;
  // A failed job stopped somewhere before succeeding; show it at the training stage.
  return status === "failed" ? 2 : 0;
}
