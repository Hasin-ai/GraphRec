import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { products } from "../../api";
import type { ProductResource } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, fmtPrice } from "../../lib/format";
import { Dialog } from "../../ui/Dialog";
import { Page } from "../../ui/Page";
import { ActionsCell, Cell, DataTable, ErrorBanner, FilterBar, Skeleton, Tag } from "../../ui/primitives";

export const AVAILABILITY = ["available", "low_stock", "out_of_stock", "discontinued"];

export function eligibility(p: ProductResource): { served: boolean; why: string } {
  if (!p.is_active) return { served: false, why: "Inactive: excluded from serving" };
  if (p.availability_status === "out_of_stock" || p.availability_status === "discontinued") return { served: false, why: `${p.availability_status}: excluded from serving` };
  return { served: true, why: "" };
}

export function DisableProductDialog({ product, onClose, onDone }: { product: ProductResource; onClose: () => void; onDone: (updated: ProductResource) => void }) {
  return (
    <Dialog
      title={`Disable ${product.external_id}`}
      width={560}
      confirmLabel="Disable product"
      body="A disabled product stops being returned by serving immediately."
      consequence="The record is retained and can be re-enabled by an update that sets it active again."
      facts={[
        { label: "Title", value: product.title },
        { label: "Availability", value: product.availability_status },
      ]}
      onConfirm={async () => onDone(await products.disable(product.external_id))}
      onClose={onClose}
    />
  );
}

export function ProductsPage() {
  const list = useResource(() => products.list(), []);
  const { can } = useSession();
  const { flash } = useToast();
  const navigate = useNavigate();
  const [category, setCategory] = useState("all categories");
  const [avail, setAvail] = useState("all availability");
  const [q, setQ] = useState("");
  const [disabling, setDisabling] = useState<ProductResource | null>(null);
  const writable = can("catalog:write");

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const p of list.data?.items ?? []) if (p.category) set.add(p.category);
    return ["all categories", ...Array.from(set).sort()];
  }, [list.data]);

  const filtered = (list.data?.items ?? []).filter((p) => {
    if (category !== "all categories" && p.category !== category) return false;
    if (avail !== "all availability" && p.availability_status !== avail) return false;
    const needle = q.trim().toLowerCase();
    return !needle || `${p.external_id} ${p.title}`.toLowerCase().includes(needle);
  });

  const rows = filtered.map((p) => {
    const e = eligibility(p);
    return (
      <tr key={p.id}>
        <td>
          <Link to={`/products/${encodeURIComponent(p.external_id)}`} className="td-mono">
            {p.external_id}
          </Link>
        </td>
        <Cell sub={e.served ? undefined : e.why}>{p.title}</Cell>
        <Cell muted>{p.category ?? "—"}</Cell>
        <Cell mono align="right">
          {fmtPrice(p.price)}
        </Cell>
        <td>
          <Tag tone={p.is_active ? "ok" : "neu"}>{p.is_active ? "active" : "inactive"}</Tag>
        </td>
        <Cell mono>{p.availability_status}</Cell>
        <td>
          <Tag tone={e.served ? "ok" : "warn"}>{e.served ? "served" : "ineligible"}</Tag>
        </td>
        <Cell mono>{fmtDateTime(p.updated_at)}</Cell>
        <ActionsCell
          actions={[
            { label: "Open", onClick: () => navigate(`/products/${encodeURIComponent(p.external_id)}`) },
            { label: "Disable", disabled: !p.is_active || !writable, reason: !writable ? "Requires catalog:write." : p.is_active ? undefined : "Already disabled.", onClick: () => setDisabling(p) },
          ]}
        />
      </tr>
    );
  });

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Products" }]}
      kicker="Catalog"
      title="Products"
      subtitle="The catalog GraphRec serves from. Ineligible products are never returned by serving, whatever the model predicts."
      actions={
        writable
          ? [
              { label: "Add product", variant: "primary", onClick: () => navigate("/products/new") },
              { label: "Synchronize", onClick: () => navigate("/products/sync") },
            ]
          : []
      }
    >
      {list.error ? <ErrorBanner error={list.error} /> : null}
      <FilterBar
        filters={[
          { id: "cat", label: "Category", value: category, onChange: setCategory, options: categories },
          { id: "avail", label: "Availability", value: avail, onChange: setAvail, options: ["all availability", ...AVAILABILITY] },
          { id: "q", label: "Search", value: q, onChange: setQ, placeholder: "identifier or title" },
        ]}
        onClear={() => {
          setCategory("all categories");
          setAvail("all availability");
          setQ("");
        }}
      />
      {list.loading && !list.data ? (
        <Skeleton />
      ) : (
        <DataTable
          minWidth={1180}
          columns={["External id", "Title", "Category", { label: "Price", align: "right" }, "Active", "Availability", "Serving", "Updated", { label: "", align: "right" }]}
          rows={rows}
          count={`${filtered.length} of ${list.data?.total ?? 0}`}
          empty={
            list.data && list.data.total > 0
              ? { title: "No products match this filter", body: "Clear the filter to see the whole catalog." }
              : { title: "No products yet", body: "Synchronize your catalog to populate it.", action: writable ? { label: "Synchronize catalog", onClick: () => navigate("/products/sync") } : undefined }
          }
        />
      )}
      {disabling ? (
        <DisableProductDialog
          product={disabling}
          onClose={() => setDisabling(null)}
          onDone={(updated) => {
            setDisabling(null);
            list.setData((prev) => (prev ? { ...prev, items: prev.items.map((x) => (x.id === updated.id ? updated : x)) } : prev));
            flash(`${updated.external_id} disabled.`);
          }}
        />
      ) : null}
    </Page>
  );
}
