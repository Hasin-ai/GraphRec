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
