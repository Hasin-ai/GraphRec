/**
 * `/admin/audit` — the whole estate's history.
 *
 * The same six columns as the tenant view and one more: `tenant_id`. That is
 * the entire difference the `audit` permission buys, and it is worth stating
 * plainly — an operator with this permission can see that a tenant existed and
 * what happened to it, and still cannot see inside it. There is no `details`
 * field on the row for the reason the server gives: an audit permission is a
 * licence to read the history, not whatever a handler once put in a jsonb
 * column.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { platformAuditQuery } from '../../api/hooks/platform';
import type { AuditRow } from '../../api/hooks/platform';
import { QueryState } from '../../components/QueryState';
import { Badge, FilterBar, Pagination, Select, Table } from '../../ui';
import type { Column } from '../../ui';
import { ABSENT, formatDateTime, humanise } from '../../lib/format';

const PAGE_SIZE = 25;
const FIRST_PAGE = 1;

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

const OUTCOME_OPTIONS = ['success', 'failure', 'denied'].map((value) => ({
  value,
  label: humanise(value),
}));

export function AdminAuditRoute() {
  const [action, setAction] = useState('');
  const [outcome, setOutcome] = useState('');
  const [page, setPage] = useState(FIRST_PAGE);
  const query = useQuery(
    platformAuditQuery({
      action: action || undefined,
      outcome: outcome || undefined,
      offset: (page - FIRST_PAGE) * PAGE_SIZE,
    }),
  );

  const columns: readonly Column<AuditRow>[] = [
    { key: 'when', header: 'When', cell: (row) => formatDateTime(row.occurred_at) },
    {
      key: 'tenant',
      header: 'Tenant',
      cell: (row) =>
        row.tenant_id ? <Link to={`/admin/tenants/${row.tenant_id}`}>Open</Link> : ABSENT,
    },
    {
      key: 'who',
      header: 'Who',
      cell: (row) =>
        row.actor_id ? (
          <>
            {humanise(row.actor_type)} <code>{row.actor_id}</code>
          </>
        ) : (
          humanise(row.actor_type)
        ),
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
    {
      key: 'correlation',
      header: 'Correlation',
      // The one column that makes this page usable during an incident: it is
      // the reference a failure row on `/admin/status` carries, so the two
      // pages can be joined by hand.
      cell: (row) => (row.correlation_ref ? <code>{row.correlation_ref}</code> : ABSENT),
    },
  ];

  const filtered = action !== '' || outcome !== '';
  const reset = () => {
    setAction('');
    setOutcome('');
    setPage(FIRST_PAGE);
  };

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Platform audit</h1>
        <p className="page__lede">
          Everything consequential across every tenant, including what operators did. Entries are
          never edited or removed.
        </p>
      </div>

      <FilterBar onReset={filtered ? reset : undefined}>
        <Select
          label="Action"
          value={action}
          placeholder="Any action"
          options={ACTION_OPTIONS}
          onChange={(event) => {
            setAction(event.target.value);
            setPage(FIRST_PAGE);
          }}
        />
        <Select
          label="Outcome"
          value={outcome}
          placeholder="Any outcome"
          options={OUTCOME_OPTIONS}
          onChange={(event) => {
            setOutcome(event.target.value);
            setPage(FIRST_PAGE);
          }}
        />
      </FilterBar>

      <QueryState
        query={query}
        shape="table"
        columns={columns.length}
        label="the platform audit trail"
        isEmpty={(data) => data.total === 0 && !filtered}
        empty={{
          headline: 'Nothing recorded yet',
          body: 'Registering a tenant, changing its status or granting an override all appear here.',
        }}
      >
        {(data) => (
          <>
            <Table
              caption="Platform audit entries"
              columns={columns}
              rows={data.entries}
              rowKey={(row) =>
                `${row.occurred_at}-${row.action}-${row.resource_ref ?? ''}-${row.actor_id ?? ''}`
              }
              empty="No entry matches those filters."
            />
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />
          </>
        )}
      </QueryState>
    </div>
  );
}
