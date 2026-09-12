const dateTime = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const dateOnly = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "2-digit", day: "2-digit" });
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
