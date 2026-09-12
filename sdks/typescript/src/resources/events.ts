import { chunkItems } from "../batching.js";
import { MAX_EVENT_ID_LENGTH } from "../constants.js";
import { APIError, InputValidationError } from "../errors.js";
import { newId } from "../ids.js";
import type { EventBatch, EventBatchResult, EventInput, EventReceipt, PreparedEvent } from "../types.js";
import { Resource, toIso } from "./base.js";

/** Settle the identifier and shape of an event for the wire. */
export function prepareEvent(input: EventInput): PreparedEvent {
  if (!input || typeof input !== "object") throw new InputValidationError("An event must be an object");
  const eventType = String(input.event_type ?? "").trim();
  if (!eventType || eventType.length > 48) throw new InputValidationError("event_type must be 1-48 characters");
  const eventId = input.event_id === undefined ? newId("evt") : String(input.event_id);
  if (!eventId || eventId.length > MAX_EVENT_ID_LENGTH) throw new InputValidationError(`event_id must be 1-${MAX_EVENT_ID_LENGTH} characters`);
  const context = input.context ?? {};
  if (!context || typeof context !== "object" || Array.isArray(context)) throw new InputValidationError(`Event ${JSON.stringify(eventId)}: context must be an object`);
  const prepared: PreparedEvent = { event_id: eventId, event_type: eventType, context };
  if (input.user_id !== undefined) prepared.user_id = input.user_id;
  if (input.external_product_id !== undefined) prepared.external_product_id = input.external_product_id;
  const occurredAt = toIso(input.occurred_at);
  if (occurredAt !== undefined) {
    if (Number.isNaN(new Date(occurredAt).getTime())) throw new InputValidationError(`Event ${JSON.stringify(eventId)}: occurred_at is not a valid timestamp`);
    prepared.occurred_at = occurredAt;
  }
  return prepared;
}

export function mergeBatchResults(batches: readonly EventBatch[]): EventBatchResult {
  const merged: EventBatchResult = { accepted_count: 0, duplicate_count: 0, rejected_count: 0, batches: [...batches], request_count: batches.length };
  for (const b of batches) {
    merged.accepted_count += b.accepted_count;
    merged.duplicate_count += b.duplicate_count;
    merged.rejected_count += b.rejected_count;
  }
  return merged;
}

export class Events extends Resource {
  /**
   * Send one interaction event (`POST /v1/events`). A repeated `event_id` is
   * confirmed as a duplicate (`receipt.duplicate === true`), never an error.
   */
  async create(event: EventInput): Promise<EventReceipt> {
    return this.client.request<EventReceipt>("events.create", { json: prepareEvent(event) });
  }

  /**
   * Send many events (`POST /v1/events/batches`), split to fit the server's
   * body limit. Counts are summed across requests; on failure the thrown
   * `APIError` carries `partialResult` with the batches applied so far.
   */
  async createBatch(events: Iterable<EventInput>): Promise<EventBatchResult> {
    const prepared = Array.from(events, prepareEvent);
    if (!prepared.length) throw new InputValidationError("createBatch() needs at least one event");
    const chunks = chunkItems(prepared, { envelopeKey: "events", maxBytes: this.client.maxBodyBytes, maxItems: this.client.maxBatchItems, describe: "Event" });
    const batches: EventBatch[] = [];
    for (const chunk of chunks) {
      try {
        batches.push(await this.client.request<EventBatch>("events.create_batch", { json: { events: chunk } }));
      } catch (error) {
        if (error instanceof APIError) error.partialResult = mergeBatchResults(batches);
        throw error;
      }
    }
    return mergeBatchResults(batches);
  }

  async listBatches(): Promise<EventBatch[]> {
    return this.client.request<EventBatch[]>("events.list_batches");
  }

  async getBatch(batchId: string): Promise<EventBatch> {
    return this.client.request<EventBatch>("events.get_batch", { params: { batch_id: batchId } });
  }
}
