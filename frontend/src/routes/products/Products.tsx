/**
 * `/products` — the catalogue list.
 *
 * Two columns carry the whole page: `eligible`, and the sentence saying why
 * not. §5 puts eligibility in the database as a generated column so that the
 * recommender and this table cannot disagree about what may be served; the
 * console's job is to display the answer, never to compute one. Nothing here
 * reads `active`, `availability` and `price` and decides for itself.
 */

import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useProducts } from '../../api/hooks/catalogue';
import type { Product } from '../../api/hooks/catalogue';
import { QueryState } from '../../components/QueryState';
import { Button, FilterBar, Input, Pagination, Select, Table, ToneBadge } from '../../ui';
import type { Column } from '../../ui';
import { formatDate, humanise } from '../../lib/format';

const PAGE_SIZE = 25;

const AVAILABILITY_OPTIONS = [
  { value: 'in_stock', label: 'In stock' },
  { value: 'low_stock', label: 'Low stock' },
  { value: 'out_of_stock', label: 'Out of stock' },
];

export function ProductsRoute() {
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [availability, setAvailability] = useState('');
  const [page, setPage] = useState(0);

  const query = useProducts({
    q: q || undefined,
    availability: availability || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });

  const columns: readonly Column<Product>[] = [
    {
      key: 'title',
      header: 'Title',
      cell: (row) => (
        <Link to={`/products/${encodeURIComponent(row.external_id)}`}>{row.title}</Link>
      ),
    },
    { key: 'external_id', header: 'Your ID', cell: (row) => <code>{row.external_id}</code> },
    { key: 'category', header: 'Category', cell: (row) => row.category ?? '—' },
    { key: 'price', header: 'Price', cell: (row) => row.price ?? '—' },
    {
      key: 'availability',
      header: 'Availability',
      cell: (row) => humanise(row.availability),
    },
    {
      key: 'eligible',
      header: 'Recommendable',
      cell: (row) => (
        <ToneBadge tone={row.eligible ? 'ok' : 'warn'}>
          {row.eligible ? 'yes' : 'no'}
        </ToneBadge>
      ),
    },
    {
      key: 'why',
      header: 'Why not',
      // The server's sentence, verbatim. A product excluded for a reason the
      // console paraphrases is a support ticket about the paraphrase.
      cell: (row) => row.ineligibility ?? row.exclusion_reason ?? '—',
    },
    { key: 'updated', header: 'Updated', cell: (row) => formatDate(row.updated_at) },
  ];

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Catalogue</h1>
        <p className="page__lede">
          What may be recommended. A product is recommendable when it is active, in stock and
          priced — the database decides that, and this column is its answer.
        </p>
      </div>

      <div className="action-row">
        <Button onClick={() => navigate('/products/new')}>Add product</Button>
        <Button variant="secondary" onClick={() => navigate('/products/sync')}>
          Bulk sync
        </Button>
      </div>

      <FilterBar
        onReset={
          q || availability
            ? () => {
                setQ('');
                setAvailability('');
                setPage(0);
              }
            : undefined
        }
      >
        <Input
          label="Search"
          value={q}
          placeholder="Title or ID"
          onChange={(event) => {
            setQ(event.target.value);
            setPage(0);
          }}
        />
        <Select
          label="Availability"
          value={availability}
          placeholder="Any"
          options={AVAILABILITY_OPTIONS}
          onChange={(event) => {
            setAvailability(event.target.value);
            setPage(0);
          }}
        />
      </FilterBar>

      <QueryState
        query={query}
        shape="table"
        columns={columns.length}
        label="the catalogue"
        isEmpty={(data) => data.total === 0 && !q && !availability}
        empty={{
          headline: 'No products yet',
          body: 'Add one by hand to see the shape, or sync your whole catalogue in one request.',
          action: <Button onClick={() => navigate('/products/sync')}>Bulk sync</Button>,
        }}
      >
        {(data) => (
          <>
            <Table
              caption="Products"
              columns={columns}
              rows={data.products}
              rowKey={(row) => row.external_id}
              empty="No product matches those filters."
            />
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={data.total}
              onPage={setPage}
            />
          </>
        )}
      </QueryState>
    </div>
  );
}
