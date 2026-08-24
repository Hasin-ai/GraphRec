/**
 * §10: loading is a skeleton for lists and detail panels, "never a bare
 * spinner on a full page". The shape is given in tokens so a skeleton in the
 * dark theme is a dark grey block rather than a light one.
 */
export interface SkeletonProps {
  width?: string;
  height?: string;
  count?: number;
}

export function Skeleton({ width = '100%', height = 'var(--space-4)', count = 1 }: SkeletonProps) {
  return (
    <div aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <div
          key={index}
          className="skeleton"
          style={{ width, height, marginBottom: 'var(--space-2)' }}
        />
      ))}
    </div>
  );
}

/** A table body's worth of skeleton, sized to the column count. */
export function TableSkeleton({ columns, rows = 5 }: { columns: number; rows?: number }) {
  return (
    <tbody aria-hidden="true">
      {Array.from({ length: rows }, (_, row) => (
        <tr key={row}>
          {Array.from({ length: columns }, (_, column) => (
            <td key={column}>
              <div className="skeleton" style={{ height: 'var(--space-4)' }} />
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  );
}

/** The polite announcement that goes with a skeleton, for readers who cannot see it. */
export function LoadingAnnouncement({ what }: { what: string }) {
  return (
    <span className="visually-hidden" role="status">
      Loading {what}
    </span>
  );
}
