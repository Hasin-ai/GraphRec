import { Check, MAX_EVENTS_PER_BATCH, MAX_EXTERNAL_ID } from '../bounds.js';
import type { Transport } from '../transport.js';
import { instant } from '../types.js';
import type { CallOptions, EventBatchInput, EventInput, EventReceipt, Submission } from '../types.js';
import { decodeSubmission } from './submissions.js';
import type { WireSubmission } from './submissions.js';

const EVENT_TYPES = ['view', 'add_to_cart', 'purchase', 'remove_from_cart'] as const;

function wireEvent(event: EventInput): Record<string, unknown> {
  return {
    event_id: event.eventId,
    customer_id: event.customerId,
    external_product_id: event.externalProductId,
    event_type: event.eventType,
    occurred_at: instant(event.occurredAt),
    ...(event.value === undefined ? {} : { value: event.value }),
    ...(event.context === undefined ? {} : { context: event.context }),
  };
}

function checkEvent(check: Check, event: EventInput, prefix: string): void {
  check
    .text(`${prefix}event_id`, event.eventId, MAX_EXTERNAL_ID)
    .text(`${prefix}customer_id`, event.customerId, MAX_EXTERNAL_ID)
    .text(`${prefix}external_product_id`, event.externalProductId, MAX_EXTERNAL_ID)
    .enum(`${prefix}event_type`, event.eventType, EVENT_TYPES)
    .instant(`${prefix}occurred_at`, event.occurredAt);
  if (event.eventType === undefined) {
    check.text(`${prefix}event_type`, undefined, MAX_EXTERNAL_ID);
  }
}

/**
 * Interaction events, on the control plane.
 *
 * Two shapes and two idempotency mechanisms, which is deliberate and worth
 * knowing: a single event is keyed on `event_id` and a repeat comes back `200
 * duplicate_confirmed` with the time the first one arrived; a batch is keyed on
 * `batch_id` and a repeat returns the original submission rather than draining
 * the collection twice. In both cases a repeat is a **success** — there is no
 * 409 anywhere on this surface, because an integration retrying after a timeout
 * has done nothing wrong (`apps/control_api/routers/ingestion.py`).
 *
 * Both keys are your arguments and neither is generated here. A generated
 * `batchId` would be different on every attempt, so the retry the SDK performs
 * on your behalf would be a second submission of the same events under a new key
 * — the deduplication the backend offers, silently disabled by the convenience
 * the SDK added.
 */
export class Events {
  readonly #transport: Transport;

  constructor(transport: Transport) {
    this.#transport = transport;
  }

  /** One interaction. Answers `200` whether it is new or a confirmed repeat. */
  async submit(event: EventInput, options?: CallOptions): Promise<EventReceipt> {
    const check = new Check();
    checkEvent(check, event, '');
    check.done('An event');

    const wire = await this.#transport.send<{
      event_id: string;
      status: EventReceipt['status'];
      first_received_at: string | null;
    }>({
      method: 'POST',
      path: '/v1/events',
      idempotent: true,
      ...(options === undefined ? {} : { options }),
      body: wireEvent(event),
    });

    return {
      eventId: wire.event_id,
      status: wire.status,
      firstReceivedAt: wire.first_received_at ?? null,
    };
  }

  /**
   * Up to 5,000 interactions, accepted for processing.
   *
   * Returns the submission at `202`, before any of it has been applied. Use
   * `submissions.wait` for the counts and the per-item rejections.
   */
  async submitBatch(batch: EventBatchInput, options?: CallOptions): Promise<Submission> {
    const check = new Check()
      .text('batch_id', batch.batchId, MAX_EXTERNAL_ID)
      .collection('events', batch.events, MAX_EVENTS_PER_BATCH);
    batch.events?.forEach((event, index) => checkEvent(check, event, `events[${index}].`));
    check.done('An event batch');

    const wire = await this.#transport.send<WireSubmission>({
      method: 'POST',
      path: '/v1/events/batches',
      idempotent: true,
      ...(options === undefined ? {} : { options }),
      body: { batch_id: batch.batchId, events: batch.events.map(wireEvent) },
    });
    return decodeSubmission(wire);
  }
}
