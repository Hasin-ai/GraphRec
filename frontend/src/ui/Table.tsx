import type { ReactNode } from 'react';
import { TableSkeleton } from './Skeleton';

export interface Column<Row> {
  key: string;
  header: string;
  /** Present when the column can be sorted; the value is what the server wants. */
  sortKey?: string;
  align?: 'left' | 'right';
  cell: (row: Row) => ReactNode;
}

export interface TableProps<Row> {
  caption: string;
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  loading?: boolean;
  /** Rendered in place of the body when there are no rows and none are loading. */
  empty?: ReactNode;
  sort?: { key: string; direction: 'asc' | 'desc' };
  onSort?: (key: string) => void;
}

/**
 * The dominant surface (§11), so it gets one treatment and every list uses it:
 * sticky header, hairline separators with none after the last row, state as a
 * `Badge`, actions right-aligned, and the whole thing scrolling in its own
 * container when it is wider than the page.
 */
export function Table<Row>({
  caption,
  columns,
  rows,
  rowKey,
  loading = false,
  empty,
  sort,
  onSort,
}: TableProps<Row>) {
  if (!loading && rows.length === 0 && empty) return <>{empty}</>;

  return (
    <div className="table-scroll">
      <table className="table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => {
              const sorted = sort && column.sortKey === sort.key;
              return (
                <th
                  key={column.key}
                  scope="col"
                  className={column.align === 'right' ? 'table__actions' : undefined}
                  aria-sort={
                    sorted ? (sort.direction === 'asc' ? 'ascending' : 'descending') : undefined
                  }
                >
                  {column.sortKey && onSort ? (
                    <button
                      type="button"
                      className="table__sort"
                      onClick={() => onSort(column.sortKey!)}
                    >
                      {column.header}
                      <span aria-hidden="true">
                        {sorted ? (sort.direction === 'asc' ? '▲' : '▼') : '↕'}
                      </span>
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        {loading ? (
          <TableSkeleton columns={columns.length} />
        ) : (
          <tbody>
            {rows.map((row) => (
              <tr key={rowKey(row)}>
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={column.align === 'right' ? 'table__actions' : undefined}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        )}
      </table>
    </div>
  );
}
