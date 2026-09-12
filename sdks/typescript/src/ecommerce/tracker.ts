/**
 * Buffered event tracking for storefront backends.
 *
 *     const tracker = new EventTracker(client, { batchSize: 50, flushIntervalMs: 5000 });
 *     tracker.view("customer-42", "sku-123", { sessionId: "sess-9" });
 *     tracker.addToCart("customer-42", "sku-123", { quantity: 2, price: "19.90" });
 *     tracker.purchase("customer-42", "sku-123", { orderId: "ORD-1001", quantity: 2 });
 *     await tracker.close();   // remaining events are flushed
 *
 * Events are sent with `POST /v1/events/batches` (split to fit the 16 KiB body
 * limit). Because each event carries a stable `event_id`, re-sending a batch
 * after a failure never double-counts.
 */
import type { GraphRec } from "../client.js";
import type { EventBatchResult, EventInput, EventType, JsonObject, PreparedEvent } from "../types.js";
import { EventBuilder, type CartOptions, type EventOptions, type PurchaseOptions, type RatingOptions } from "./builders.js";
import { prepareEvent } from "../resources/events.js";

export type ErrorHandler = (error: unknown, events: PreparedEvent[]) => void | Promise<void>;

export interface EventTrackerOptions {
  /** Flush automatically once this many events are queued (default 100). */
  batchSize?: number;
  /** Milliseconds between background flushes; omit or `null` for no timer. */
  flushIntervalMs?: number | null;
  /** Oldest events are dropped beyond this bound (default 10 000). */
  maxQueueSize?: number;
  /**
   * Called when a flush fails; the events are then discarded. Without a
   * handler, failed events are re-queued once and retried on the next flush.
   */
  onError?: ErrorHandler;
  defaultContext?: JsonObject;
}

export class EventTracker {
  readonly batchSize: number;
  readonly maxQueueSize: number;
  private readonly client: GraphRec;
  private readonly builder: EventBuilder;
  private readonly onError?: ErrorHandler;
  private readonly queue: PreparedEvent[] = [];
  private readonly retried = new Set<string>();
  private droppedCount = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private flushing: Promise<EventBatchResult | null> | null = null;
  private closed = false;

  constructor(client: GraphRec, options: EventTrackerOptions = {}) {
    this.client = client;
    this.batchSize = options.batchSize ?? 100;
    this.maxQueueSize = options.maxQueueSize ?? 10_000;
    if (this.batchSize < 1) throw new RangeError("batchSize must be >= 1");
    if (this.maxQueueSize < 1) throw new RangeError("maxQueueSize must be >= 1");
    this.onError = options.onError;
    this.builder = new EventBuilder({ defaultContext: options.defaultContext });
    if (options.flushIntervalMs) {
      this.timer = setInterval(() => this.backgroundFlush(), options.flushIntervalMs);
      // Never keep a process alive only to flush analytics.
      (this.timer as { unref?: () => void }).unref?.();
    }
  }

  /** Events waiting to be sent. */
  get pending(): number {
    return this.queue.length;
  }

  /** Events dropped because the queue was full. */
  get dropped(): number {
    return this.droppedCount;
  }

  /** Queue any event; returns the prepared event with its settled `event_id`. */
  track(event: EventInput | PreparedEvent): PreparedEvent {
    return this.enqueue(prepareEvent(event));
  }

  view(userId: string | null, productId: string, options?: EventOptions): PreparedEvent {
    return this.enqueue(this.builder.view(userId, productId, options));
  }
  click(userId: string | null, productId: string, options?: EventOptions): PreparedEvent {
    return this.enqueue(this.builder.click(userId, productId, options));
  }
  addToCart(userId: string | null, productId: string, options?: CartOptions): PreparedEvent {
    return this.enqueue(this.builder.addToCart(userId, productId, options));
  }
  removeFromCart(userId: string | null, productId: string, options?: CartOptions): PreparedEvent {
    return this.enqueue(this.builder.removeFromCart(userId, productId, options));
  }
  purchase(userId: string | null, productId: string, options?: PurchaseOptions): PreparedEvent {
    return this.enqueue(this.builder.purchase(userId, productId, options));
  }
  rating(userId: string | null, productId: string, rating: number, options?: RatingOptions): PreparedEvent {
    return this.enqueue(this.builder.rating(userId, productId, rating, options));
  }
  search(userId: string | null, query: string, options?: EventOptions): PreparedEvent {
    return this.enqueue(this.builder.search(userId, query, options));
  }
  addToWishlist(userId: string | null, productId: string, options?: EventOptions): PreparedEvent {
    return this.enqueue(this.builder.addToWishlist(userId, productId, options));
  }
  custom(eventType: EventType, args: { userId?: string | null; productId?: string | null } & EventOptions, extra?: JsonObject): PreparedEvent {
    return this.enqueue(this.builder.build(eventType, args, extra));
  }

  /**
   * Send everything queued so far. Resolves once every event that was queued
   * when `flush()` was called has been sent: a flush already in flight is
   * awaited first, then anything queued in the meantime goes out in a new
   * request. Only one request is ever in flight per tracker.
   */
  async flush(): Promise<EventBatchResult | null> {
    let result: EventBatchResult | null = null;
    while (this.flushing) result = await this.flushing;
    if (!this.queue.length) return result;
    const run = this.doFlush().finally(() => {
      if (this.flushing === run) this.flushing = null;
    });
    this.flushing = run;
    return run;
  }

  /** Stop the timer and flush what remains. */
  async close(): Promise<void> {
    this.closed = true;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    await this.flush();
  }

  async [Symbol.asyncDispose](): Promise<void> {
    await this.close();
  }

  /** Timer- and size-triggered flushes must never surface as unhandled rejections. */
  private backgroundFlush(): void {
    this.flush().catch((error: unknown) => {
      if (!this.onError) console.warn("GraphRec EventTracker flush failed; events re-queued once:", error instanceof Error ? error.message : error);
    });
  }

  private enqueue(event: PreparedEvent): PreparedEvent {
    if (this.closed) throw new Error("EventTracker is closed");
    if (this.queue.length >= this.maxQueueSize) {
      this.queue.shift();
      this.droppedCount += 1;
    }
    this.queue.push(event);
    if (this.queue.length >= this.batchSize) this.backgroundFlush();
    return event;
  }

  private async doFlush(): Promise<EventBatchResult | null> {
    const batch = this.queue.splice(0, this.queue.length);
    if (!batch.length) return null;
    try {
      const result = await this.client.events.createBatch(batch);
      for (const e of batch) this.retried.delete(e.event_id);
      return result;
    } catch (error) {
      if (this.onError) {
        await this.onError(error, batch);
        return null;
      }
      // Re-queue once; a second failure for the same events drops them.
      const keep = batch.filter((e) => !this.retried.has(e.event_id));
      for (const e of keep) this.retried.add(e.event_id);
      this.droppedCount += batch.length - keep.length;
      this.queue.unshift(...keep.slice(Math.max(0, keep.length - this.maxQueueSize)));
      throw error;
    }
  }
}
