import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { billing, products } from "../../api";
import type { ProductResource } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useQueryState } from "../../hooks/useQueryState";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDate, fmtDateTimeFull, fmtNumber, fmtPrice, humanize } from "../../lib/format";
import { naturalCompare } from "../../lib/labels";
import { Dialog } from "../../ui/Dialog";
import { Page } from "../../ui/Page";
import { DataTable, ErrorBanner, Skeleton, Tag } from "../../ui/primitives";

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

/** "Item 42" for external ID "42" is a placeholder title: don't print the ID twice. */
const isPlaceholderTitle = (p: ProductResource) => p.title.trim() === `Item ${p.external_id}`;
const hasPrice = (p: ProductResource) => Number(p.price) > 0;

function Pager({ page, total, loading, onPage }: { page: number; total: number; loading: boolean; onPage: (n: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total ? (page - 1) * PAGE_SIZE + 1 : 0;
  const to = Math.min(total, page * PAGE_SIZE);
  return <div className="pager">
    <span className="pos">{fmtNumber(from)}–{fmtNumber(to)} of {fmtNumber(total)}</span>
    <button type="button" className="btn btn-secondary btn-sm" onClick={() => onPage(page - 1)} disabled={page <= 1 || loading}>Previous</button>
    <span className="pos">Page {fmtNumber(page)} of {fmtNumber(pages)}</span>
    <button type="button" className="btn btn-secondary btn-sm" onClick={() => onPage(page + 1)} disabled={page >= pages || loading}>Next</button>
  </div>;
}

export function ProductsPage() {
  const [params, setParams] = useSearchParams();
  const requested = Number(params.get('page') ?? 1);
  const page = Number.isSafeInteger(requested) && requested > 0 ? requested : 1;
  const list = useResource(() => products.list({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE }), [page]);
  const { can } = useSession();
  const usage = useResource(() => can('usage:read') ? billing.usage() : Promise.resolve(null), [can('usage:read')]);
  const { flash } = useToast();
  const navigate = useNavigate();
  const [avail, setAvail] = useQueryState('availability', 'all availability');
  const [q, setQ] = useQueryState('q', '');
  const [disabling, setDisabling] = useState<ProductResource | null>(null);
  const writable = can('catalog:write');
  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const stored = usage.data?.dimensions?.find(d => d.type === 'stored_products');
  const overLimit = !!stored && stored.limit !== null && stored.used >= stored.limit;
  const filtered = items
    .filter(p => (avail === 'all availability' || p.availability_status === avail) && (!q.trim() || `${p.external_id} ${p.title}`.toLowerCase().includes(q.trim().toLowerCase())))
    .slice().sort((a, b) => naturalCompare(a.external_id, b.external_id));
  // Columns that are empty for every product on the page are hidden, with one explanation (audit PR-3).
  const showCategory = items.some(p => p.category);
  const showPrice = items.some(hasPrice);
  const placeholderCatalog = items.length > 0 && !showCategory && !showPrice;
  const setPage = (value: number) => setParams(previous => { const next = new URLSearchParams(previous); next.set('page', String(value)); return next; });
  const clear = () => setParams(previous => { const next = new URLSearchParams(previous); next.delete('q'); next.delete('availability'); return next; }, { replace: true });
  const addReason = !writable ? undefined : overLimit ? 'Over the product limit' : undefined;

  return <Page crumbs={[{ label: 'Home', to: '/home' }, { label: 'Products' }]} title="Products"
    subtitle={total ? `${fmtNumber(total)} products in the catalog used for recommendations.` : 'Manage the catalog used for recommendations.'}
    actions={writable ? [{ label: 'Synchronize catalog', onClick: () => navigate('/products/sync') }, { label: 'Add product', variant: overLimit ? 'secondary' : 'primary', disabled: overLimit, reason: addReason, onClick: () => navigate('/products/new') }] : []}>
    {overLimit && stored ? <div className="callout warn" role="status"><div><strong>Catalog is {fmtNumber(stored.used - (stored.limit ?? 0))} products over its plan limit ({fmtNumber(stored.limit)}).</strong>
      <p>New products are blocked; existing products can still be updated and keep serving. <a href="/usage" onClick={e => { e.preventDefault(); navigate('/usage'); }}>Review usage and limits</a></p></div></div> : null}

    <form className="toolbar" role="search" onSubmit={e => { e.preventDefault(); const id = q.trim(); if (id && !filtered.length) navigate(`/products/${encodeURIComponent(id)}`); }}>
      <div className="search">
        <label htmlFor="f-q">Search this page</label>
        <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.6" /><path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
        <input id="f-q" className="input" value={q} onChange={e => setQ(e.target.value)} placeholder="Title or external ID" />
      </div>
      <div className="field"><label htmlFor="f-avail">Availability on this page</label>
        <select id="f-avail" className="input" value={avail} onChange={e => setAvail(e.target.value)}>{['all availability', ...AVAILABILITY].map(o => <option key={o} value={o}>{o === 'all availability' ? 'All availability' : humanize(o)}</option>)}</select></div>
      <button type="button" className="btn btn-secondary" onClick={clear} disabled={!q && avail === 'all availability'}>Clear</button>
      <p className="hint">Filters the {fmtNumber(items.length)} products shown on this page. No match? Press Enter to open the product with that exact external ID.</p>
    </form>

    {list.error ? <ErrorBanner error={list.error} onRetry={list.reload} /> : null}
    {list.data && total ? <div className="table-head-bar"><span className="count">{filtered.length === items.length ? `Showing ${fmtNumber(items.length)}` : `${fmtNumber(filtered.length)} of ${fmtNumber(items.length)} match`} on this page</span><Pager page={page} total={total} loading={list.loading} onPage={setPage} /></div> : null}
    {!list.data ? list.loading ? <Skeleton /> : null : <div className="table-mobile-cards"><DataTable minWidth={showCategory || showPrice ? 760 : 560}
      columns={['Product', ...(showCategory ? ['Category'] : []), ...(showPrice ? [{ label: 'Price', align: 'right' as const }] : []), 'Availability', 'Updated', { label: '', align: 'right' }]}
      rows={filtered.map(p => { const e = eligibility(p); const to = `/products/${encodeURIComponent(p.external_id)}`; return <tr key={p.id}>
        <td><Link to={to}>{p.title}</Link>{isPlaceholderTitle(p) ? null : <div className="sub mono">{p.external_id}</div>}</td>
        {showCategory ? <td data-hide-mobile className="td-muted">{p.category ?? 'Not set'}</td> : null}
        {showPrice ? <td data-hide-mobile className="num">{hasPrice(p) ? fmtPrice(p.price) : <span className="td-muted">Not set</span>}</td> : null}
        <td><Tag tone={e.served ? 'ok' : 'neu'}>{p.is_active ? humanize(p.availability_status) : 'Inactive'}</Tag>{e.served ? null : <div className="sub">Not recommended</div>}</td>
        <td data-hide-mobile><time dateTime={p.updated_at} title={fmtDateTimeFull(p.updated_at)}>{fmtDate(p.updated_at)}</time></td>
        <td className="right"><details className="row-menu"><summary aria-label={`Actions for ${p.title}`}><svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16"><circle cx="3.5" cy="8" r="1.3" fill="currentColor" /><circle cx="8" cy="8" r="1.3" fill="currentColor" /><circle cx="12.5" cy="8" r="1.3" fill="currentColor" /></svg></summary>
          <div><button type="button" onClick={() => navigate(to)}>Open</button>{writable ? <button type="button" className="danger" disabled={!p.is_active} title={p.is_active ? undefined : 'Already disabled.'} onClick={e => { (e.currentTarget.closest('details') as HTMLDetailsElement).open = false; setDisabling(p); }}>Disable…</button> : null}</div></details></td>
      </tr>; })}
      footer={total > PAGE_SIZE ? <Pager page={page} total={total} loading={list.loading} onPage={setPage} /> : undefined}
      empty={total ? { title: 'No products match on this page', body: 'Clear the filters, choose another page, or press Enter in search to open an exact external ID.' } : { title: 'No products yet', body: 'Add products or synchronize your catalog to start recommending.', action: writable ? { label: 'Synchronize catalog', onClick: () => navigate('/products/sync') } : undefined }} /></div>}
    {placeholderCatalog ? <div className="table-note"><p>These products were created from an interaction log, so they have no category or price yet. Those columns are hidden until products carry them. {writable ? <Link to="/products/sync">Synchronize your catalog</Link> : null}{writable ? ' to add titles, categories and prices.' : null}</p></div> : null}
    {disabling ? <DisableProductDialog product={disabling} onClose={() => setDisabling(null)} onDone={updated => { setDisabling(null); list.setData(previous => previous ? { ...previous, items: previous.items.map(p => p.id === updated.id ? updated : p) } : previous); flash(`${updated.external_id} disabled.`); }} /> : null}
  </Page>;
}
