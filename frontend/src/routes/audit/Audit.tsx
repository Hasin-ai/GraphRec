/**
 * `/audit` — who did what, in this tenant.
 *
 * This is the redacted view. `AuditLogRow` has no `metadata` field at all,
 * which is deliberate on the server side: platform audit rows carry free-form
 * detail and a tenant-facing view cannot promise what is in it. So the page
 * shows the five facts it can stand behind — when, who, what, to what, and how
 * it went — and nothing more.
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { auditQuery } from '../../api/hooks/operations';
import type { S } from '../../api/schema';
import { QueryState } from '../../components/QueryState';
import { Badge, FilterBar, Pagination, Select, Table } from '../../ui';
import type { Column } from '../../ui';
import { formatDateTime, humanise } from '../../lib/format';

const PAGE_SIZE = 25;

/** The eight actions the tenant realm records, from the generated enum. */
const ACTION_OPTIONS = [
  'credential',
  'training',
  'activation',
  'rollback',
  'quota',
  'tenant',
  'access',
  'security',
].map((value) => ({ value, label: humanise(value) }));

export function AuditRoute() {
  const [action, setAction] = useState('');
  const [page, setPage] = useState(0);
  const query = useQuery(
    auditQuery({
      action: action || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
  );

  const columns: readonly Column<S['AuditLogRow']>[] = [
    { key: 'when', header: 'When', cell: (row) => formatDateTime(row.occurred_at) },
    {
      key: 'who',
      header: 'Who',
      // The actor *type*, not a name. A platform administrator acting on this
      // tenant appears as exactly that, which is the fact a tenant needs and
      // the most a tenant is owed.
      cell: (row) => humanise(row.actor_type),
    },
    { key: 'what', header: 'Action', cell: (row) => humanise(row.action) },
    {
      key: 'resource',
      header: 'Resource',
      cell: (row) =>
        row.resource_ref ? (
          <>
            {humanise(row.resource_type)} <code>{row.resource_ref}</code>
          </>
        ) : (
          humanise(row.resource_type)
        ),
    },
    {
      key: 'outcome',
      header: 'Outcome',
      cell: (row) => <Badge domain="outcome" value={row.outcome} />,
    },
  ];

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Audit</h1>
        <p className="page__lede">
          Everything consequential that happened in this organisation, including anything the
          platform did on your behalf. Entries are never edited or removed.
        </p>
      </div>

      <FilterBar
        onReset={
          action
            ? () => {
                setAction('');
                setPage(0);
              }
            : undefined
        }
      >
        <Select
          label="Action"
          value={action}
          placeholder="Any action"
          options={ACTION_OPTIONS}
          onChange={(event) => {
            setAction(event.target.value);
            setPage(0);
          }}
        />
      </FilterBar>

      <QueryState
        query={query}
        shape="table"
        columns={columns.length}
        label="the audit trail"
        isEmpty={(data) => data.total === 0 && !action}
        empty={{
          headline: 'Nothing recorded yet',
          body: 'Inviting somebody, issuing a credential or activating a model all appear here.',
        }}
      >
        {(data) => (
          <>
            <Table
              caption="Audit entries"
              columns={columns}
              rows={data.entries}
              rowKey={(row) => `${row.occurred_at}-${row.action}-${row.resource_ref ?? ''}`}
              empty="No entry for that action."
            />
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </>
        )}
      </QueryState>
    </div>
  );
}
