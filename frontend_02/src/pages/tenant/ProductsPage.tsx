import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { products } from "../../api";
import type { ProductResource } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useQueryState } from "../../hooks/useQueryState";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, fmtPrice, humanize } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Page } from "../../ui/Page";
import { ActionsCell, Cell, DataTable, ErrorBanner, FilterBar, Skeleton, Tag } from "../../ui/primitives";

export const AVAILABILITY = ["available", "unavailable", "out_of_stock", "discontinued"];
export function eligibility(p: ProductResource): { served: boolean; why: string } {
  if (!p.is_active) return { served: false, why: "Inactive: excluded from recommendations" };
  if (p.availability_status !== "available") return { served: false, why: `${humanize(p.availability_status)}: excluded from recommendations` };
  return { served: true, why: "" };
}
export function DisableProductDialog({ product, onClose, onDone }: { product: ProductResource; onClose: () => void; onDone: (updated: ProductResource) => void }) {
  return <Dialog title={`Disable ${product.external_id}`} width={560} confirmLabel="Disable product" body="This product will be excluded from new recommendations." consequence="The record is retained. You can re-enable it by setting it active again." facts={[{ label: 'Title', value: product.title }, { label: 'Availability', value: product.availability_status }]} onConfirm={async () => onDone(await products.disable(product.external_id))} onClose={onClose} />;
}
export const PAGE_SIZE = 50;
export function ProductsPage() {
  const [params, setParams] = useSearchParams();
  const requested = Number(params.get('page') ?? 1);
  const page = Number.isSafeInteger(requested) && requested > 0 ? requested : 1;
  const list = useResource(() => products.list({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }), [page]);
  const { can } = useSession();
  const { flash } = useToast();
  const navigate = useNavigate();
  const [avail, setAvail] = useQueryState('availability', 'all availability');
  const [q, setQ] = useQueryState('q', '');
  const [exactId, setExactId] = useState('');
  const [disabling, setDisabling] = useState<ProductResource | null>(null);
  const writable = can('catalog:write');
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const filtered = items.filter(p => (avail === 'all availability' || p.availability_status === avail) && (!q.trim() || `${p.external_id} ${p.title}`.toLowerCase().includes(q.trim().toLowerCase())));
  const setPage = (value: number) => setParams(previous => { const next = new URLSearchParams(previous); next.set('page', String(value)); return next; });
  return <Page crumbs={[{ label: 'Home', to: '/home' }, { label: 'Products' }]} title="Products" subtitle="Manage the catalog used for recommendations." actions={writable ? [{ label: 'Add product', variant: 'primary', onClick: () => navigate('/products/new') }, { label: 'Synchronize', onClick: () => navigate('/products/sync') }] : []}>
    <div className="catalog-tools"><FilterBar filters={[
      { id: 'q', label: 'Search this page', value: q, onChange: setQ, placeholder: 'Identifier or title' },
      { id: 'avail', label: 'Availability on this page', value: avail, onChange: setAvail, options: ['all availability', ...AVAILABILITY] },
    ]} onClear={() => setParams(previous => { const next = new URLSearchParams(previous); next.delete('q'); next.delete('availability'); return next; }, { replace: true })} />
    <form className="exact-lookup" onSubmit={e => { e.preventDefault(); if (exactId.trim()) navigate(`/products/${encodeURIComponent(exactId.trim())}`); }}>
      <label htmlFor="exact-product">Find anywhere by external ID</label><div className="row"><input id="exact-product" className="input" value={exactId} onChange={e => setExactId(e.target.value)} /><button className="btn btn-secondary" disabled={!exactId.trim()}>Find product</button></div>
    </form></div>
    {list.error ? <ErrorBanner error={list.error} onRetry={list.reload} /> : null}
    {!list.data ? list.loading ? <Skeleton /> : null : <DataTable minWidth={860} columns={['Product', 'Category', { label: 'Price', align: 'right' }, 'Availability', 'Updated', { label: 'Actions', align: 'right' }]}
      rows={filtered.map(p => { const e = eligibility(p); return <tr key={p.id}>
        <td><Link to={`/products/${encodeURIComponent(p.external_id)}`}>{p.title}</Link><div className="sub mono">{p.external_id}</div></td>
        <Cell muted>{p.category ?? '—'}</Cell><Cell mono align="right">{fmtPrice(p.price)}</Cell>
        <Cell sub={e.served ? 'Eligible for recommendations' : 'Excluded from recommendations'}><Tag tone={e.served ? 'ok' : 'neu'}>{p.is_active ? humanize(p.availability_status) : 'Inactive'}</Tag></Cell>
        <Cell>{fmtDateTime(p.updated_at)}</Cell>
        <ActionsCell actions={[{ label: 'Open', onClick: () => navigate(`/products/${encodeURIComponent(p.external_id)}`) }, ...(writable ? [{ label: 'Disable', disabled: !p.is_active, reason: p.is_active ? undefined : 'Already disabled.', onClick: () => setDisabling(p) }] : [])]} />
      </tr>; })}
      count={total ? `${filtered.length} shown · page ${page} of ${Math.max(1, Math.ceil(total / PAGE_SIZE))} · ${total} products` : '0 products'}
      footer={<div className="pagination"><button type="button" className="btn btn-secondary" onClick={() => setPage(page - 1)} disabled={page <= 1 || list.loading}>Previous</button><button type="button" className="btn btn-secondary" onClick={() => setPage(page + 1)} disabled={page * PAGE_SIZE >= total || list.loading}>Next</button></div>}
      empty={total ? { title: 'No products match on this page', body: 'Clear the filters, choose another page, or find a product by its exact external ID.' } : { title: 'No products yet', body: 'Add products or synchronize your catalog.', action: writable ? { label: 'Synchronize catalog', onClick: () => navigate('/products/sync') } : undefined }} />}
    {disabling ? <DisableProductDialog product={disabling} onClose={() => setDisabling(null)} onDone={updated => { setDisabling(null); list.setData(previous => previous ? { ...previous, items: previous.items.map(p => p.id === updated.id ? updated : p) } : previous); flash(`${updated.external_id} disabled.`); }} /> : null}
  </Page>;
}
