import type { ReactNode } from 'react';

export interface StatCardProps {
  label: string;
  /** A measured figure, or `null` where the platform could not measure one. */
  value: ReactNode;
  note?: ReactNode;
}

/**
 * A measurement gap is not a zero. When the server returns `null` for a
 * quantity it also returns a reason, and the card shows an em dash with that
 * reason underneath rather than inventing a number — which is the whole point
 * of the `MeasurementStatus` enum reaching the frontend at all.
 */
export function StatCard({ label, value, note }: StatCardProps) {
  const missing = value === null || value === undefined;
  return (
    <div className="stat">
      <div className="stat__label">{label}</div>
      <div className="stat__value">{missing ? <span aria-label="Not measured">—</span> : value}</div>
      {note ? <div className="stat__note">{note}</div> : null}
    </div>
  );
}
