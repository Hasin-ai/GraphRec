import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { products } from "../../api";
import { isApiError } from "../../api/client";
import type { ProductResource, ProductUpsert } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { useToast } from "../../hooks/useToast";
import { fmtDateTime, fmtPrice } from "../../lib/format";
import { Field, Form, Select, TextArea, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { DefinitionList, ErrorBanner, Footnote, Skeleton, Tag } from "../../ui/primitives";
import { AVAILABILITY, DisableProductDialog, eligibility } from "./ProductsPage";
import { NotFoundPage } from "../errors/ErrorPages";

interface Draft {
  external_id: string;
  title: string;
  category: string;
  price: string;
  availability: string;
  description: string;
  metadata: string;
  is_active: boolean;
}

const EMPTY: Draft = { external_id: "", title: "", category: "", price: "0.00", availability: "available", description: "", metadata: "", is_active: true };

function fromResource(p: ProductResource): Draft {
  return {
    external_id: p.external_id,
    title: p.title,
    category: p.category ?? "",
    price: fmtPrice(p.price),
    availability: p.availability_status,
    description: p.description ?? "",
    metadata: Object.keys(p.metadata ?? {}).length ? JSON.stringify(p.metadata, null, 2) : "",
    is_active: p.is_active,
  };
}

function validate(d: Draft, requireId: boolean): { errors: Record<string, string>; payload?: ProductUpsert } {
  const errors: Record<string, string> = {};
  if (requireId && !d.external_id.trim()) errors.external_id = "Required.";
  if (!d.title.trim()) errors.title = "Required.";
  const price = Number(d.price);
  if (d.price.trim() === "" || !Number.isFinite(price) || price < 0) errors.price = "Enter a non-negative decimal.";
  let metadata: Record<string, unknown> = {};
  if (d.metadata.trim()) {
    try {
      const parsed = JSON.parse(d.metadata) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) errors.metadata = "Must be a JSON object.";
      else metadata = parsed as Record<string, unknown>;
    } catch {
      errors.metadata = "Not valid JSON.";
    }
  }
  if (Object.keys(errors).length) return { errors };
  return {
    errors,
    payload: {
      external_id: d.external_id.trim(),
      title: d.title.trim(),
      category: d.category.trim() || null,
      price: d.price.trim(),
      availability_status: d.availability,
      description: d.description.trim() || null,
      is_active: d.is_active,
      metadata,
    },
  };
}

function ProductFields({ draft, set, errors, idEditable }: { draft: Draft; set: (patch: Partial<Draft>) => void; errors: Record<string, string>; idEditable: boolean }) {
  return (
    <>
      <Field id="external_id" label="External product id" error={errors.external_id} hint={idEditable ? "Your own identifier, unique within this tenant. It is also the idempotency key for later updates." : undefined}>
        <TextInput id="external_id" value={draft.external_id} onChange={(v) => set({ external_id: v })} mono placeholder="SKU-0001" disabled={!idEditable} />
      </Field>
      <Field id="title" label="Title" error={errors.title}>
        <TextInput id="title" value={draft.title} onChange={(v) => set({ title: v })} />
      </Field>
      <Field id="category" label="Category">
        <TextInput id="category" value={draft.category} onChange={(v) => set({ category: v })} placeholder="Hardware" />
      </Field>
      <Field id="price" label="Price" error={errors.price}>
        <TextInput id="price" value={draft.price} onChange={(v) => set({ price: v })} mono placeholder="8.40" />
      </Field>
      <Field id="availability" label="Availability">
        <Select id="availability" value={draft.availability} onChange={(v) => set({ availability: v })} options={AVAILABILITY} />
      </Field>
      <Field id="is_active" label="Active">
        <Select id="is_active" value={draft.is_active ? "active" : "inactive"} onChange={(v) => set({ is_active: v === "active" })} options={["active", "inactive"]} />
      </Field>
      <Field id="description" label="Description" wide>
        <TextArea id="description" rows={3} value={draft.description} onChange={(v) => set({ description: v })} />
      </Field>
      <Field id="metadata" label="Metadata (optional JSON object)" wide error={errors.metadata} hint="Free-form attributes such as brand, kept with the product.">
        <TextArea id="metadata" rows={3} value={draft.metadata} onChange={(v) => set({ metadata: v })} mono placeholder='{ "brand": "Northgate" }' />
      </Field>
    </>
  );
}

function mapError(caught: unknown, setFields: (f: Record<string, string>) => void): FormError {
  if (isApiError(caught) && caught.code === "validation_failed") {
    const mapped: Record<string, string> = {};
    for (const f of caught.fields) mapped[f.field] = f.message;
    setFields(mapped);
    return { title: "Correct the highlighted field", body: caught.fields.length ? "Then submit again." : caught.message };
  }
  if (isApiError(caught) && caught.status === 409) return { title: "That identifier is already in use", body: caught.message };
  if (isApiError(caught) && caught.status === 429) return { title: "Quota or rate limit reached", body: caught.message, tone: "warn" };
  if (isApiError(caught) && caught.status === 403) return { title: "Not permitted", body: "Your credential does not grant catalog:write." };
  return { title: "The product could not be saved", body: "Try again shortly." };
}

export function ProductNewPage() {
  const navigate = useNavigate();
  const { flash } = useToast();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  async function submit() {
    const { errors, payload } = validate(draft, true);
    setFieldErrors(errors);
    if (!payload) {
      setError({ title: "Correct the highlighted field", body: "Then submit again." });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await products.put(payload.external_id, payload);
      flash(`Product ${created.external_id} saved.`);
      navigate(`/products/${encodeURIComponent(created.external_id)}`);
    } catch (caught) {
      setError(mapError(caught, setFieldErrors));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page crumbs={[{ label: "Home", to: "/home" }, { label: "Products", to: "/products" }, { label: "New" }]} kicker="Catalog" title="Add product" subtitle="Creates or updates the product with this external identifier. PUT is idempotent: repeating it applies the same state again.">
      <Form onSubmit={submit} error={error} submitLabel="Save product" busy={busy} width={760} secondary={{ label: "Cancel", to: "/products" }}>
        <ProductFields draft={draft} set={set} errors={fieldErrors} idEditable />
      </Form>
      <Footnote>Use Synchronize Catalog for more than a handful of products.</Footnote>
    </Page>
  );
}

export function ProductDetailPage() {
  const { productId = "" } = useParams();
  const navigate = useNavigate();
  const { can } = useSession();
  const { flash } = useToast();
  const product = useResource(() => products.get(productId), [productId]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const writable = can("catalog:write");

  useEffect(() => {
    if (product.data) setDraft(fromResource(product.data));
  }, [product.data]);

  if (product.error && isApiError(product.error) && product.error.status === 404) return <NotFoundPage />;
  if (!product.data || !draft) {
    return (
      <Page crumbs={[{ label: "Home", to: "/home" }, { label: "Products", to: "/products" }, { label: productId, mono: true }]} kicker="Catalog" title={productId}>
        {product.error ? <ErrorBanner error={product.error} /> : <Skeleton />}
      </Page>
    );
  }
  const p = product.data;
  const e = eligibility(p);
  const set = (patch: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...patch } : d));

  async function submit() {
    if (!draft) return;
    const { errors, payload } = validate(draft, false);
    setFieldErrors(errors);
    if (!payload) {
      setError({ title: "Correct the highlighted field", body: "Then submit again." });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await products.put(p.external_id, { ...payload, external_id: p.external_id });
      product.setData(updated);
      flash(`Product ${updated.external_id} updated.`);
    } catch (caught) {
      setError(mapError(caught, setFieldErrors));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page
      crumbs={[{ label: "Home", to: "/home" }, { label: "Products", to: "/products" }, { label: p.external_id, mono: true }]}
      kicker="Catalog"
      title={p.title}
      badge={<Tag tone={e.served ? "ok" : "warn"}>{e.served ? "served" : "ineligible"}</Tag>}
      subtitle={e.served ? undefined : e.why}
      actions={[{ label: "Disable product", disabled: !p.is_active || !writable, reason: !writable ? "Requires catalog:write." : p.is_active ? undefined : "This product is already disabled.", onClick: () => setDisabling(true) }]}
    >
      <DefinitionList
        items={[
          { label: "External product id", value: p.external_id, mono: true, copy: p.external_id },
          { label: "Category", value: p.category ?? "—" },
          { label: "Price", value: fmtPrice(p.price), mono: true },
          { label: "Active", badge: <Tag tone={p.is_active ? "ok" : "neu"}>{p.is_active ? "active" : "inactive"}</Tag> },
          { label: "Availability", value: p.availability_status, mono: true },
          { label: "Created at", value: fmtDateTime(p.created_at), mono: true },
          { label: "Updated at", value: fmtDateTime(p.updated_at), mono: true },
        ]}
      />
      {writable ? (
        <Form onSubmit={submit} error={error} submitLabel="Update product" busy={busy} width={760} secondary={{ label: "Back to products", to: "/products" }}>
          <ProductFields draft={draft} set={set} errors={fieldErrors} idEditable={false} />
        </Form>
      ) : (
        <Footnote>Your credential reads the catalog but does not hold catalog:write, so no edits are offered here.</Footnote>
      )}
      {disabling ? (
        <DisableProductDialog
          product={p}
          onClose={() => setDisabling(false)}
          onDone={(updated) => {
            setDisabling(false);
            product.setData(updated);
            flash(`${updated.external_id} disabled.`);
            navigate("/products");
          }}
        />
      ) : null}
    </Page>
  );
}
