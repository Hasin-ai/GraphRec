/**
 * Dates, numbers and the absent value.
 *
 * One rule, applied everywhere: **an absent value renders as an em dash, never
 * as a zero and never as a blank cell.** §10 requires it for measurements
 * ("unavailable measurements show a safe status, never a blank or a zero") and
 * it is right for every other column too — a table cell that is empty because
 * nothing has happened is indistinguishable from one that is empty because
 * something broke.
 *
 * Timestamps are rendered in the reader's own zone by `Intl`, and always with
 * a `<time>` element carrying the ISO string, so the exact instant is
 * recoverable from the markup even where the display is coarse.
 */

export const ABSENT = '—';

const DATE = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
});

const DATE_TIME = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

export function formatDate(value: string | null | undefined): string {
  if (!value) return ABSENT;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? ABSENT : DATE.format(parsed);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return ABSENT;
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? ABSENT : DATE_TIME.format(parsed);
}

/** How long ago, in words. For "last transition" and "measured 4 minutes ago". */
export function formatAgo(value: string | null | undefined): string {
  if (!value) return ABSENT;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return ABSENT;
  const seconds = Math.round((Date.now() - parsed.valueOf()) / 1000);
  const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['second', 60],
    ['minute', 60],
    ['hour', 24],
    ['day', 30],
    ['month', 12],
  ];
  let amount = seconds;
  for (const [unit, step] of units) {
    if (Math.abs(amount) < step) return relative.format(-amount, unit);
    amount = Math.round(amount / step);
  }
  return relative.format(-amount, 'year');
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return ABSENT;
  return new Intl.NumberFormat().format(value);
}

/**
 * A quality measure, to three decimals.
 *
 * Three because Recall@10 differences between two model versions live in the
 * third — rounding to two would render an improvement and a regression
 * identically, on the page whose entire purpose is telling them apart.
 */
export function formatMetric(value: number | null | undefined): string {
  if (value === null || value === undefined) return ABSENT;
  return value.toFixed(3);
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return ABSENT;
  return `${(value * 100).toFixed(1)}%`;
}

/** `snake_case` as words, for enum values with no hand-written label. */
export function humanise(value: string | null | undefined): string {
  if (!value) return ABSENT;
  return value.replace(/_/g, ' ');
}
