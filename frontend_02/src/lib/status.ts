export type Tone = "ok" | "warn" | "danger" | "info" | "neu";

/**
 * State enumerations and their fixed semantic colours (the prototype's GROUPS map),
 * narrowed to the values the API actually emits.
 */
const GROUPS: Record<string, Record<string, Tone>> = {
  job: { queued: "info", running: "info", cancelled: "neu", succeeded: "ok", failed: "danger" },
  model: { eligible: "neu", active: "ok", retired: "neu", archived: "neu" },
  deploy: { stopped: "neu", available: "ok" },
  tenant: { deleted: "neu", pending: "info", suspended: "warn", deleting: "warn", active: "ok" },
  key: { active: "ok", expired: "warn", revoked: "danger" },
  batch: { completed: "ok" },
  outcome: { success: "ok", succeeded: "ok", denied: "warn", failure: "danger", failed: "danger" },
  sev: { info: "info", low: "info", warning: "warn", medium: "warn", error: "danger", high: "danger", critical: "danger" },
  platform: { healthy: "ok", ok: "ok", disabled: "neu", degraded: "warn", online: "ok", connected: "ok", unavailable: "danger", not_deployed: "neu" },
};

export function toneFor(group: keyof typeof GROUPS | string, value: string): Tone {
  return GROUPS[group]?.[value] ?? "neu";
}

/** The states a training job passes through, in order. Jobs run synchronously,
 * so a client usually observes only the terminal state. */
export const JOB_STATES = ["queued", "running", "succeeded", "failed", "cancelled"] as const;
