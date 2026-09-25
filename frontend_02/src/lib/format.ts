const dateTime = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZoneName: "short",
});
const dateOnly = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" });
const number = new Intl.NumberFormat();

export const DASH = "—";

export function fmtDateTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return DASH;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : dateTime.format(d).replace(",", "");
}

export function fmtDate(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return DASH;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : dateOnly.format(d);
}

export function fmtNumber(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return DASH;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? number.format(n) : String(value);
}

export function fmtBytes(value: number): string {
  if (!Number.isFinite(value)) return DASH;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = value;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export function fmtQuantity(value: number, unit: "count" | "seconds" | "bytes" | "minutes"): string {
  if (unit === "bytes") return fmtBytes(value);
  if (unit === "seconds") return `${fmtNumber(value)} s`;
  if (unit === "minutes") return `${fmtNumber(value)} min`;
  return fmtNumber(value);
}

export function fmtPercent(fraction: number, digits = 2): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function fmtPrice(value: number | string): string {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : String(value);
}

/**
 * A snake_case API identifier rendered as a reading label
 * ("accepted_events" -> "Accepted events"). The raw identifier stays available
 * for operators who integrate against it; this is what the screen shows.
 */
export function humanize(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function shortId(id: string, length = 8): string {
  return id.length > length ? `${id.slice(0, length)}…` : id;
}

export function relativeSeconds(from: number, to = Date.now()): string {
  const s = Math.max(0, Math.round((to - from) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${Math.round(m / 60)} h ago`;
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Flatten a metrics map one entry per leaf ("validation.NDCG@10", "source.artifact").
 * Ranking measures (Hit@k, NDCG@k) are listed first so summaries lead with quality.
 */
export function flattenMetrics(metrics: Record<string, unknown> | null | undefined): [string, unknown][] {
  const out: [string, unknown][] = [];
  const walk = (value: unknown, prefix: string) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const [k, v] of Object.entries(value as Record<string, unknown>)) walk(v, prefix ? `${prefix}.${k}` : k);
    } else {
      out.push([prefix, Array.isArray(value) ? value.join(", ") : value]);
    }
  };
  walk(metrics ?? {}, "");
  const rank = (key: string) => (/(^|\.)(hit|ndcg)@\d+$/i.test(key) ? 0 : 1);
  return out.sort((a, b) => rank(a[0]) - rank(b[0]));
}
