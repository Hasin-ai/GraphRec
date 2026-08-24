/**
 * `/admin/tenants` — the estate.
 *
 * The list an operator works from, and the only place in the console where a
 * tenant is named in a path. §13 forbids a tenant identifier in a *tenant*
 * route; this is the platform realm, where a tenant is a row rather than a
 * scope, and naming one is the whole point.
 *
 * Paginated, unlike every tenant-realm list: the estate has no bound. The page
 * size comes back with the data rather than being assumed here, because the
 * server is the one enforcing it.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { tenantsQuery } from '../../api/hooks/platform';
import type { TenantRow } from '../../api/hooks/platform';
import { QueryState } from '../../components/QueryState';
import { Badge, FilterBar, Input, Pagination, Select, Table } from '../../ui';
import type { Column } from '../../ui';
import { formatDate } from '../../lib/format';

const STATUS_OPTIONS = [
  { value: '', label: 'Any status' },
  { value: 'pending', label: 'Pending' },
  { value: 'active', label: 'Active' },
  { value: 'suspended', label: 'Suspended' },
  { value: 'deleting', label: 'Deleting' },
  { value: 'deleted', label: 'Deleted' },
] as const;

export function AdminTenantsRoute() {
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const tenants = useQuery(tenantsQuery({ status, q: search, offset }));

  const columns: readonly Column<TenantRow>[] = [
    {
      key: 'name',
      header: 'Tenant',
      cell: (row) => <Link to={`/admin/tenants/${row.tenant_id}`}>{row.tenant_name}</Link>,
    },
    { key: 'code', header: 'Code', cell: (row) => <code>{row.tenant_code}</code> },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => <Badge domain="tenant" value={row.status} />,
    },
    // A tenant with no plan is a real state — registration does not assign one
    // — and it renders as an em dash rather than as a blank, because a blank
    // cell reads as a rendering fault.
    { key: 'plan', header: 'Plan', cell: (row) => row.plan_code ?? '—' },
    { key: 'created', header: 'Registered', cell: (row) => formatDate(row.created_at) },
  ];

  function changeFilter(apply: () => void) {
    apply();
    // Page 4 of a different filter is not page 4 of anything.
    setOffset(0);
  }

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Tenants</h1>
        <p className="page__lede">
          Every tenant account in this installation. Opening one shows the sections your
          permissions cover; the rest are named and withheld rather than hidden.
        </p>
      </div>

      <FilterBar
        onReset={() =>
          changeFilter(() => {
            setSearch('');
            setStatus('');
          })
        }
      >
        <Input
          label="Search"
          value={search}
          onChange={(event) => changeFilter(() => setSearch(event.target.value))}
          hint="Matches the name or the code."
        />
        <Select
          label="Status"
          value={status}
          options={STATUS_OPTIONS}
          onChange={(event) => changeFilter(() => setStatus(event.target.value))}
        />
      </FilterBar>

      <QueryState
        query={tenants}
        shape="table"
        columns={columns.length}
        label="the estate"
        isEmpty={(data) => data.tenants.length === 0}
        empty={{
          headline: 'No tenants match',
          body: 'Nothing in the estate matches these filters. Clear them to see every account.',
        }}
      >
        {(data) => (
          <>
            <p className="checklist__progress">
              {data.tenants.length} of {data.total}
            </p>
            <Table
              caption="Tenant accounts"
              columns={columns}
              rows={data.tenants}
              rowKey={(row) => row.tenant_id}
            />
            <Pagination
              page={Math.floor(data.offset / data.limit) + 1}
              pageSize={data.limit}
              total={data.total}
              onPage={(page) => setOffset((page - 1) * data.limit)}
            />
          </>
        )}
      </QueryState>
    </div>
  );
}
