import { useState } from "react";
import { Link } from "react-router-dom";
import { products } from "../../api";
import { isApiError } from "../../api/client";
import type { ProductBulkUpsertResponse, ProductUpsert } from "../../api/types";
import { fmtNumber } from "../../lib/format";
import { Field, Form, TextArea, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { Badge, Cell, DefinitionList, Footnote, Panel, PanelTable, Stats } from "../../ui/primitives";

const EXAMPLE = `{
  "products": [
    { "external_id": "SKU-4471", "title": "Brass hinge, 75mm", "category": "Hardware", "price": "8.40", "availability_status": "available" },
    { "external_id": "SKU-4472", "title": "Brass hinge, 100mm", "category": "Hardware", "price": "9.95" }
  ]
}`;

/** Accepts {"products":[...]} or a bare array; returns the item list or a validation message. */
export function parseProductCollection(text: string): { items?: ProductUpsert[]; error?: string } {
  if (!text.trim()) return { error: "Paste a product collection." };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { error: "The collection is not valid JSON." };
  }
  const items = Array.isArray(parsed) ? parsed : (parsed as { products?: unknown })?.products;
  if (!Array.isArray(items) || !items.length) return { error: 'Provide a non-empty "products" array.' };
  if (!items.every((i) => i && typeof i === "object" && typeof (i as ProductUpsert).external_id === "string")) return { error: "Every product needs an external_id." };
  return { items: items as ProductUpsert[] };
}

export function ProductSyncPage() {
  const [payload, setPayload] = useState("");
  const [error, setError] = useState<FormError | null>(null);
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ received: number; response: ProductBulkUpsertResponse } | null>(null);

  async function submit() {
    const { items, error: parseError } = parseProductCollection(payload);
    setFieldError(parseError);
    if (!items) {
      setError({ title: "Correct the highlighted field", body: parseError ?? "" });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult({ received: items.length, response: await products.bulkUpsert(items) });
    } catch (caught) {
      if (isApiError(caught) && caught.status === 413) setError({ title: "Submission rejected: too large", body: "The request body exceeds the API limit (16 KiB by default). Split the collection and submit it in parts, or use a dataset upload.", tone: "warn" });
      else if (isApiError(caught) && caught.code === "validation_failed") setError({ title: "The collection cannot be accepted", body: caught.fields.map((f) => `${f.field}: ${f.message}`).join("; ") || caught.message });
      else if (isApiError(caught) && caught.status === 403) setError({ title: "Not permitted", body: "Your credential does not grant catalog:write." });
      else setError({ title: "Synchronization failed", body: "Try again shortly." });
    } finally {
      setBusy(false);
    }
  }

  const crumbs = [{ label: "Home", to: "/home" }, { label: "Products", to: "/products" }, { label: "Synchronize" }];

  if (result) {
    const r = result.response;
    return (
      <Page crumbs={crumbs} kicker="Phase 2 of 2" title="Synchronization applied" badge={<Badge group="outcome" value={r.rejected_count ? "denied" : "succeeded"} />} subtitle="Bulk upsert is synchronous: the counts below are the final result." actions={[{ label: "Synchronize again", variant: "primary", onClick: () => setResult(null) }]}>
        <Stats
          items={[
            { label: "Received", value: fmtNumber(result.received) },
            { label: "Accepted", value: fmtNumber(r.accepted_count) },
            { label: "Created", value: fmtNumber(r.created_count) },
            { label: "Updated", value: fmtNumber(r.updated_count) },
            { label: "Skipped", value: fmtNumber(r.skipped_count) },
            { label: "Rejected", value: fmtNumber(r.rejected_count), tone: r.rejected_count ? "danger" : undefined },
          ]}
        />
        <Panel title="Rejected items" note={`${r.failures.length} reported`} body="Failures identify the offending item and a safe reason. The accepted remainder is not discarded.">
          {r.failures.length ? (
            <PanelTable
              columns={["External id", "Reason"]}
              rows={r.failures.map((f, i) => (
                <tr key={`${f.external_id}-${i}`}>
                  <Cell mono>{f.external_id}</Cell>
                  <Cell muted>{f.reason}</Cell>
                </tr>
              ))}
            />
          ) : (
            <p className="p-body">No item was rejected.</p>
          )}
        </Panel>
        <div className="row">
          <Link className="btn btn-secondary" to="/products">
            Open products
          </Link>
        </div>
      </Page>
    );
  }

  return (
    <Page crumbs={crumbs} kicker="Phase 1 of 2" title="Synchronize catalog" subtitle="Submit a product collection. Each external identifier is upserted: new ones are created, known ones updated, and invalid items are reported without discarding the rest.">
      <Form onSubmit={submit} error={error} submitLabel="Submit synchronization" busy={busy} width={860} secondary={{ label: "Cancel", to: "/products" }}>
        <Field id="payload" label="Product collection (JSON)" wide error={fieldError} hint="Bounded by the request body limit (16 KiB by default). Larger catalogs go through a dataset upload.">
          <TextArea id="payload" rows={12} value={payload} onChange={setPayload} mono placeholder={EXAMPLE} />
        </Field>
      </Form>
      <DefinitionList
        items={[
          { label: "Required fields", value: "external_id, title", mono: true },
          { label: "Optional fields", value: "description, price, category, is_active, availability_status, metadata", mono: true },
        ]}
      />
      <Footnote>Repeating the same collection is safe: unchanged products are counted as skipped rather than applied twice.</Footnote>
    </Page>
  );
}
