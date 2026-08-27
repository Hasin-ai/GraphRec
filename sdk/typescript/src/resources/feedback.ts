import { Check, MAX_DATA_PLANE_ID } from '../bounds.js';
import type { Transport } from '../transport.js';
import type { CallOptions, FeedbackRequest, FeedbackResponse } from '../types.js';

interface WireResponse {
  request_id: string;
  received: number;
  accepted: number;
  duplicates: number;
  unknown_products: string[];
}

/** No published ceiling on the batch; the 16 KB body limit is the real bound. */
const MAX_FEEDBACK_EVENTS = 1_000;

/**
 * What happened to an answer, on the data plane.
 *
 * Three routes rather than one with a `type` field, because that is how the API
 * is shaped and collapsing them would mean inventing a discriminator the server
 * does not read. All three take the same body and all three are keyed on
 * `request_id` plus each item's `event_id`, so a retried batch is deduplicated
 * per item — `graphrec/domain/serving/feedback.py` opens by saying a retry after
 * a timeout is the normal consequence of one, not an error.
 *
 * `unknownProducts` in the reply is not a failure. It is the identifiers that
 * are not in your catalogue, which usually means the catalogue sync has not
 * caught up with the storefront, and it is worth a metric.
 */
export class Feedback {
  readonly #transport: Transport;

  constructor(transport: Transport) {
    this.#transport = transport;
  }

  /** The items you actually rendered. Without these, a click has no denominator. */
  impressions(request: FeedbackRequest, options?: CallOptions): Promise<FeedbackResponse> {
    return this.#send('/v1/feedback/impressions', request, options);
  }

  clicks(request: FeedbackRequest, options?: CallOptions): Promise<FeedbackResponse> {
    return this.#send('/v1/feedback/clicks', request, options);
  }

  /** `value` is a number here — a signal, not money. See `FeedbackEvent.value`. */
  conversions(request: FeedbackRequest, options?: CallOptions): Promise<FeedbackResponse> {
    return this.#send('/v1/feedback/conversions', request, options);
  }

  async #send(
    path: string,
    request: FeedbackRequest,
    options?: CallOptions,
  ): Promise<FeedbackResponse> {
    const check = new Check()
      .text('request_id', request.requestId, MAX_DATA_PLANE_ID)
      .collection('events', request.events, MAX_FEEDBACK_EVENTS);
    request.events?.forEach((event, index) => {
      check.text(`events[${index}].event_id`, event.eventId, MAX_DATA_PLANE_ID);
      check.text(`events[${index}].external_product_id`, event.externalProductId, MAX_DATA_PLANE_ID);
    });
    check.done('A feedback request');

    const wire = await this.#transport.send<WireResponse>({
      method: 'POST',
      path,
      // Safe: `request_id` plus each `event_id` is the deduplication key.
      idempotent: true,
      ...(options === undefined ? {} : { options }),
      body: {
        request_id: request.requestId,
        events: request.events.map((event) => ({
          event_id: event.eventId,
          external_product_id: event.externalProductId,
          ...(event.value === undefined ? {} : { value: event.value }),
        })),
      },
    });

    return {
      requestId: wire.request_id,
      received: wire.received,
      accepted: wire.accepted,
      duplicates: wire.duplicates,
      unknownProducts: wire.unknown_products,
    };
  }
}
