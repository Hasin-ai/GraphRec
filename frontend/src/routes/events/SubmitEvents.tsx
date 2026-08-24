/**
 * `/events/submit` — send one event, or a batch.
 *
 * This page exists to make the contract legible, not because anybody will run
 * their production traffic through a textarea. So it does two things a real
 * integration cannot: it shows the exact JSON being sent, and it explains what
 * `duplicate_confirmed` means the first time somebody presses the button twice.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { submitEvent, submitEventBatch } from '../../api/hooks/events';
import type { EventResult } from '../../api/hooks/events';
import type { Submission } from '../../api/hooks/catalogue';
import type { S } from '../../api/schema';
import { Banner, Button, Input, Select, Tabs, TabPanel, Textarea } from '../../ui';
import { useSubmit } from '../../lib/useSubmit';

const EVENT_TYPES = [
  { value: 'view', label: 'View' },
  { value: 'add_to_cart', label: 'Add to cart' },
  { value: 'remove_from_cart', label: 'Remove from cart' },
  { value: 'purchase', label: 'Purchase' },
];

const EXAMPLE_BATCH = `[
  {
    "event_id": "11111111-1111-4111-8111-111111111111",
    "customer_id": "customer-1",
    "external_product_id": "sku-1",
    "event_type": "view",
    "occurred_at": "2026-01-01T10:00:00Z"
  }
]`;

export function SubmitEventsRoute() {
  const [tab, setTab] = useState('one');

  return (
    <div className="page">
      <div className="page__head">
        <h1 className="page__title">Submit events</h1>
        <p className="page__lede">
          Interactions are what the model learns from. Each one carries an <code>event_id</code>{' '}
          that you choose; sending it again is confirmed rather than counted twice, so a retry after
          a timeout is always safe.
        </p>
      </div>

      <Tabs
        label="How to submit"
        tabs={[
          { id: 'one', label: 'One event' },
          { id: 'batch', label: 'Batch' },
        ]}
        active={tab}
        onChange={setTab}
      />
      <TabPanel id={tab}>{tab === 'one' ? <SingleEventForm /> : <BatchForm />}</TabPanel>
    </div>
  );
}

function SingleEventForm() {
  const [customerId, setCustomerId] = useState('');
  const [productId, setProductId] = useState('');
  const [eventType, setEventType] = useState('view');
  const [eventId, setEventId] = useState<string>(() => crypto.randomUUID());
  const [value, setValue] = useState('');
  const [result, setResult] = useState<EventResult | null>(null);

  const form = useSubmit<EventResult>(
    (body: S['SubmitEventRequest']) => submitEvent(body),
    setResult,
  );

  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        setResult(null);
        form.submit({
          event_id: eventId,
          customer_id: customerId.trim(),
          external_product_id: productId.trim(),
          event_type: eventType,
          occurred_at: new Date().toISOString(),
          value: eventType === 'purchase' && value ? String(value) : null,
        });
      }}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      {result ? (
        <Banner kind={result.status === 'accepted' ? 'success' : 'info'}>
          {result.status === 'accepted'
            ? 'Accepted.'
            : `Already had this one — first received ${result.first_received_at ?? 'earlier'}. Nothing was counted twice.`}
        </Banner>
      ) : null}

      <Input
        label="Customer ID"
        required
        value={customerId}
        error={form.fieldErrors.customer_id}
        onChange={(event) => setCustomerId(event.target.value)}
        hint="Your own identifier for the person. We never need their name or address."
      />
      <Input
        label="Product ID"
        required
        value={productId}
        error={form.fieldErrors.external_product_id}
        onChange={(event) => setProductId(event.target.value)}
        hint="Must already exist in your catalogue."
      />
      <Select
        label="Event type"
        value={eventType}
        options={EVENT_TYPES}
        error={form.fieldErrors.event_type}
        onChange={(event) => setEventType(event.target.value)}
      />
      {eventType === 'purchase' ? (
        <Input
          label="Value"
          inputMode="decimal"
          value={value}
          error={form.fieldErrors.value}
          onChange={(event) => setValue(event.target.value)}
          hint="What it sold for."
        />
      ) : null}
      <Input
        label="Event ID"
        required
        value={eventId}
        error={form.fieldErrors.event_id}
        onChange={(event) => setEventId(event.target.value)}
        hint="The idempotency key. Press submit twice with the same one to see what a retry does."
      />

      <div className="action-row">
        <Button type="submit" disabled={form.pending}>
          {form.pending ? 'Submitting…' : 'Submit event'}
        </Button>
        <Button
          type="button"
          variant="secondary"
          onClick={() => {
            setEventId(crypto.randomUUID());
            setResult(null);
          }}
        >
          New event ID
        </Button>
      </div>
    </form>
  );
}

/**
 * A batch is accepted, not applied — the response is a submission, and the
 * result is on `/submissions/:id` once the worker has been through it.
 *
 * The JSON is parsed here before sending so that a stray comma is a message
 * next to the textarea rather than a 422 about a body the reader cannot see.
 */
function BatchForm() {
  const navigate = useNavigate();
  const [text, setText] = useState(EXAMPLE_BATCH);
  const [parseError, setParseError] = useState<string | null>(null);

  const form = useSubmit<Submission>(
    (body: S['SubmitEventBatchRequest']) => submitEventBatch(body),
    (submission) => navigate(`/submissions/${submission.submission_id}`),
  );

  return (
    <form
      className="stack"
      onSubmit={(event) => {
        event.preventDefault();
        setParseError(null);
        let events: unknown[];
        try {
          const parsed: unknown = JSON.parse(text);
          if (!Array.isArray(parsed)) {
            setParseError('The batch must be a JSON array of events.');
            return;
          }
          events = parsed;
        } catch (caught) {
          setParseError(caught instanceof Error ? caught.message : 'That is not valid JSON.');
          return;
        }
        form.submit({ batch_id: crypto.randomUUID(), events });
      }}
    >
      {form.error ? <Banner kind="danger">{form.error.body.reason}</Banner> : null}
      <Textarea
        label="Events"
        rows={14}
        value={text}
        error={parseError ?? form.fieldErrors.events}
        onChange={(event) => setText(event.target.value)}
        hint="A JSON array. The batch is accepted for processing and you are taken to its submission."
      />
      <div className="action-row">
        <Button type="submit" disabled={form.pending}>
          {form.pending ? 'Submitting…' : 'Submit batch'}
        </Button>
      </div>
    </form>
  );
}
