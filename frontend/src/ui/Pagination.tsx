import { Button } from './Button';

export interface PaginationProps {
  page: number;
  pageSize: number;
  /** Total matching rows, when the endpoint reports one. */
  total?: number;
  /** For cursor endpoints that only say whether there is more. */
  hasNext?: boolean;
  onPage: (page: number) => void;
}

export function Pagination({ page, pageSize, total, hasNext, onPage }: PaginationProps) {
  const first = (page - 1) * pageSize + 1;
  const last = total === undefined ? page * pageSize : Math.min(page * pageSize, total);
  const forward = hasNext ?? (total !== undefined && page * pageSize < total);

  return (
    <div className="pagination">
      <Button size="sm" onClick={() => onPage(page - 1)} disabled={page <= 1}>
        Previous
      </Button>
      <span role="status">
        {total === undefined
          ? `Showing ${first}–${last}`
          : total === 0
            ? 'No rows'
            : `Showing ${first}–${last} of ${total}`}
      </span>
      <Button size="sm" onClick={() => onPage(page + 1)} disabled={!forward}>
        Next
      </Button>
    </div>
  );
}
