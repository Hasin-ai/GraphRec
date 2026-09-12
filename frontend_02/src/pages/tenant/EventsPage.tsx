import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { events } from "../../api";
import { isApiError } from "../../api/client";
import type { EventBatchResponse, EventSubmit, EventSubmitResponse } from "../../api/types";
import { useResource } from "../../hooks/useResource";
import { useSession } from "../../hooks/useSession";
import { fmtDateTime, fmtNumber } from "../../lib/format";
import { Field, Form, Select, TextArea, TextInput, type FormError } from "../../ui/Form";
import { Page } from "../../ui/Page";
import { ActionsCell, Badge, Cell, DataTable, DefinitionList, ErrorBanner, FilterBar, Footnote } from "../../ui/primitives";

const EVENT_TYPES = ["view", "add_to_cart", "purchase", "remove_from_cart", "search", "click"];

const BATCH_EXAMPLE = `{
  "events": [
    { "event_id": "ev-1", "event_type": "view", "user_id": "cus-1", "external_product_id": "SKU-4471", "occurred_at": "2026-08-14T09:41:02Z" },
    { "event_id": "ev-2", "event_type": "purchase", "user_id": "cus-1", "external_product_id": "SKU-4471" }
  ]
}`;

export function parseEventCollection(text: string): { items?: EventSubmit[]; error?: string } {
  if (!text.trim()) return { error: "Paste an event collection." };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { error: "The collection is not valid JSON." };
  }
  const items = Array.isArray(parsed) ? parsed : (parsed as { events?: unknown })?.events;
  if (!Array.isArray(items) || !items.length) return { error: 'Provide a non-empty "events" array.' };
  if (!items.every((i) => i && typeof i === "object" && typeof (i as EventSubmit).event_id === "string" && typeof (i as EventSubmit).event_type === "string")) return { error: "Every event needs an event_id and an event_type." };
  return { items: items as EventSubmit[] };
}

function mapError(caught: unknown): FormError {
  if (isApiError(caught) && caught.status === 413) return { title: "Batch rejected: too large", body: "The request body exceeds the API limit (16 KiB by default). Split the collection or use a dataset upload.", tone: "warn" };
  if (isApiError(caught) && caught.code === "validation_failed") return { title: "The submission cannot be accepted", body: caught.fields.map((f) => `${f.field}: ${f.message}`).join("; ") || caught.message };
  if (isApiError(caught) && caught.status === 403) return { title: "Not permitted", body: "Your credential does not grant events:write." };
  if (isApiError(caught) && caught.status === 429) return { title: "Quota or rate limit reached", body: caught.message, tone: "warn" };
  return { title: "Submission failed", body: "Try again shortly." };
}

type Result = { kind: "single"; event: EventSubmitResponse; type: string } | { kind: "batch"; batch: EventBatchResponse; received: number };

function RecentBatches() {
  const { can } = useSession();
  const navigate = useNavigate();
  const batches = useResource(() => (can("events:read") ? events.listBatches() : Promise.resolve([])), [can("events:read")]);
  if (!can("events:read")) return null;
  const rows = (batches.data ?? []).map((b) => (
    <tr key={b.id}>
      <td>
        <Link to={`/submissions/${b.id}`} className="td-mono">
          {b.id}
        </Link>
      </td>
      <td>
        <Badge group="batch" value={b.status} />
      </td>
      <Cell mono align="right">
        {fmtNumber(b.accepted_count)}
      </Cell>
      <Cell mono align="right">
        {fmtNumber(b.duplicate_count)}
      </Cell>
      <Cell mono align="right">
        {fmtNumber(b.rejected_count)}
      </Cell>
      <Cell mono>{fmtDateTime(b.created_at)}</Cell>
      <ActionsCell actions={[{ label: "Open", onClick: () => navigate(`/submissions/${b.id}`) }]} />
    </tr>
  ));
  return (
    <>
      {batches.error ? <ErrorBanner error={batches.error} /> : null}
      <DataTable
        title="Recent batch submissions"
        minWidth={900}
        columns={["Submission", "Status", { label: "Accepted", align: "right" }, { label: "Duplicates", align: "right" }, { label: "Rejected", align: "right" }, "Submitted at", { label: "", align: "right" }]}
        rows={rows}
        count={`${rows.length} batches`}
        empty={{ title: "No batch submissions yet", body: "Batches you submit here appear with their result counts." }}
      />
    </>
  );
}

export function EventsPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState("single event");
  const [single, setSingle] = useState({ event_id: "", user_id: "", external_product_id: "", event_type: "view", occurred_at: "", context: "" });
  const [batch, setBatch] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<FormError | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const set = (patch: Partial<typeof single>) => setSingle((s) => ({ ...s, ...patch }));

  async function submitSingle() {
    const errors: Record<string, string> = {};
    if (!single.event_id.trim()) errors.event_id = "Required: it is the idempotency key.";
    let context: Record<string, unknown> | undefined;
    if (single.context.trim()) {
      try {
        const parsed = JSON.parse(single.context) as unknown;
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) errors.context = "Must be a JSON object.";
        else context = parsed as Record<string, unknown>;
      } catch {
        errors.context = "Not valid JSON.";
      }
    }
    if (single.occurred_at.trim() && Number.isNaN(new Date(single.occurred_at).getTime())) errors.occurred_at = "Use an ISO-8601 timestamp.";
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setError({ title: "Correct the highlighted fields", body: "Then submit again." });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await events.submit({
        event_id: single.event_id.trim(),
        event_type: single.event_type,
        ...(single.user_id.trim() ? { user_id: single.user_id.trim() } : {}),
        ...(single.external_product_id.trim() ? { external_product_id: single.external_product_id.trim() } : {}),
        ...(single.occurred_at.trim() ? { occurred_at: new Date(single.occurred_at).toISOString() } : {}),
        ...(context ? { context } : {}),
      });
      setResult({ kind: "single", event: response, type: single.event_type });
    } catch (caught) {
      setError(mapError(caught));
    } finally {
      setBusy(false);
    }
  }

  async function submitBatch() {
    const { items, error: parseError } = parseEventCollection(batch);
    setFieldErrors(parseError ? { batch: parseError } : {});
    if (!items) {
      setError({ title: "Correct the highlighted field", body: parseError ?? "" });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult({ kind: "batch", batch: await events.submitBatch(items), received: items.length });
    } catch (caught) {
      setError(mapError(caught));
    } finally {
      setBusy(false);
    }
  }

  const crumbs = [{ label: "Home", to: "/home" }, { label: "Submit Events" }];

  if (result?.kind === "single") {
    const r = result.event;
    return (
      <Page crumbs={crumbs} kicker="Result" title={r.duplicate ? "Duplicate confirmed" : "Event accepted"} badge={<Badge group="outcome" value="succeeded" />} subtitle={r.duplicate ? `Event ${r.event_id} was already received and is not counted twice. This is a success outcome, not an error.` : `Event ${r.event_id} was accepted and will be included in the next dataset snapshot.`} actions={[{ label: "Submit another", variant: "primary", onClick: () => setResult(null) }]}>
        <DefinitionList
          items={[
            { label: "Event identifier", value: r.event_id, mono: true },
            { label: "Event type", value: result.type, mono: true },
            { label: "Status", value: r.duplicate ? "duplicate_confirmed" : "accepted", mono: true },
            { label: "Received at", value: fmtDateTime(r.received_at), mono: true },
          ]}
        />
      </Page>
    );
  }
  if (result?.kind === "batch") {
    const b = result.batch;
    return (
      <Page crumbs={crumbs} kicker="Result" title="Batch accepted" badge={<Badge group="batch" value={b.status} />} subtitle={`The batch was processed with the counts below.`} actions={[{ label: "Open submission result", variant: "primary", onClick: () => navigate(`/submissions/${b.id}`) }, { label: "Submit another", onClick: () => setResult(null) }]}>
        <DefinitionList
          items={[
            { label: "Submission id", value: <Link to={`/submissions/${b.id}`}>{b.id}</Link>, mono: true, copy: b.id },
            { label: "Received", value: fmtNumber(result.received), mono: true },
            { label: "Accepted", value: fmtNumber(b.accepted_count), mono: true },
            { label: "Duplicates", value: fmtNumber(b.duplicate_count), mono: true },
            { label: "Rejected", value: fmtNumber(b.rejected_count), mono: true },
            { label: "Submitted at", value: fmtDateTime(b.created_at), mono: true },
          ]}
        />
      </Page>
    );
  }

  return (
    <Page crumbs={crumbs} kicker="Ingestion" title="Submit events" subtitle="Interaction events feed the dataset snapshot a training job builds from. Single and batch share one event shape.">
      <FilterBar filters={[{ id: "mode", label: "Submission mode", value: mode, onChange: setMode, options: ["single event", "batch"] }]} onClear={() => setMode("single event")} />
      {mode === "single event" ? (
        <Form onSubmit={submitSingle} error={error} submitLabel="Submit event" busy={busy} width={860}>
          <Field id="event_id" label="Event identifier" error={fieldErrors.event_id} hint="Idempotency key. A repeat is confirmed as a duplicate.">
            <TextInput id="event_id" value={single.event_id} onChange={(v) => set({ event_id: v })} mono placeholder="ev-33810" />
          </Field>
          <Field id="event_type" label="Event type">
            <Select id="event_type" value={single.event_type} onChange={(v) => set({ event_type: v })} options={EVENT_TYPES} />
          </Field>
          <Field id="user_id" label="Customer identifier">
            <TextInput id="user_id" value={single.user_id} onChange={(v) => set({ user_id: v })} mono placeholder="cus-9931" />
          </Field>
          <Field id="external_product_id" label="External product id">
            <TextInput id="external_product_id" value={single.external_product_id} onChange={(v) => set({ external_product_id: v })} mono placeholder="SKU-6002" />
          </Field>
          <Field id="occurred_at" label="Occurred at (optional)" error={fieldErrors.occurred_at} hint="Defaults to now.">
            <TextInput id="occurred_at" value={single.occurred_at} onChange={(v) => set({ occurred_at: v })} mono placeholder="2026-08-14T09:41:02Z" />
          </Field>
          <Field id="context" label="Context (optional JSON)" wide error={fieldErrors.context}>
            <TextArea id="context" rows={3} value={single.context} onChange={(v) => set({ context: v })} mono placeholder='{ "surface": "product_page" }' />
          </Field>
        </Form>
      ) : (
        <Form onSubmit={submitBatch} error={error} submitLabel="Submit batch" busy={busy} width={860}>
          <Field id="batch" label="Event collection (JSON)" wide error={fieldErrors.batch} hint="Bounded by the request body limit (16 KiB by default).">
            <TextArea id="batch" rows={12} value={batch} onChange={setBatch} mono placeholder={BATCH_EXAMPLE} />
          </Field>
        </Form>
      )}
      <RecentBatches />
      <Footnote>Submitting an event identifier that was already received returns a duplicate confirmation rather than an error.</Footnote>
    </Page>
  );
}
