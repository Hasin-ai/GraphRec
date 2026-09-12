import { InputValidationError } from "../errors.js";
import { deterministicId } from "../ids.js";
import { prepareEvent } from "../resources/events.js";
import type { EventType, JsonObject, Money, PreparedEvent } from "../types.js";

export interface EventOptions {
  sessionId?: string;
  context?: JsonObject;
  occurredAt?: string | Date;
  eventId?: string;
}

export interface CartOptions extends EventOptions {
  quantity?: number;
  price?: Money;
  currency?: string;
}

export interface PurchaseOptions extends CartOptions {
  /** With `orderId` the event id is derived from `(orderId, line ?? productId)`, so replays never double-count. */
  orderId?: string;
  line?: number | string;
}

export interface RatingOptions extends EventOptions {
  maxRating?: number;
}

function positiveQuantity(quantity: number): void {
  if (!Number.isInteger(quantity) || quantity < 1) throw new InputValidationError("quantity must be a positive integer");
}

/** Typed constructors for common e-commerce interactions. */
export class EventBuilder {
  readonly defaultContext: JsonObject;

  constructor(options: { defaultContext?: JsonObject } = {}) {
    this.defaultContext = { ...(options.defaultContext ?? {}) };
  }

  build(eventType: EventType, args: { userId?: string | null; productId?: string | null } & EventOptions, extra: JsonObject = {}): PreparedEvent {
    const context: JsonObject = { ...this.defaultContext, ...(args.context ?? {}), ...extra };
    if (args.sessionId !== undefined) context.session_id = args.sessionId;
    return prepareEvent({
      event_type: eventType,
      user_id: args.userId ?? null,
      external_product_id: args.productId ?? null,
      context,
      occurred_at: args.occurredAt,
      event_id: args.eventId,
    });
  }

  view(userId: string | null, productId: string, options: EventOptions = {}): PreparedEvent {
    return this.build("view", { userId, productId, ...options });
  }

  click(userId: string | null, productId: string, options: EventOptions = {}): PreparedEvent {
    return this.build("click", { userId, productId, ...options });
  }

  addToCart(userId: string | null, productId: string, options: CartOptions = {}): PreparedEvent {
    const quantity = options.quantity ?? 1;
    positiveQuantity(quantity);
    return this.build("add_to_cart", { userId, productId, ...options }, cartExtra(quantity, options));
  }

  removeFromCart(userId: string | null, productId: string, options: CartOptions = {}): PreparedEvent {
    const quantity = options.quantity ?? 1;
    positiveQuantity(quantity);
    return this.build("remove_from_cart", { userId, productId, ...options }, cartExtra(quantity, options));
  }

  /** A purchased order line. Pass `orderId` so a redelivered webhook is recorded once. */
  purchase(userId: string | null, productId: string, options: PurchaseOptions = {}): PreparedEvent {
    const quantity = options.quantity ?? 1;
    positiveQuantity(quantity);
    const extra = cartExtra(quantity, options);
    const args: { userId: string | null; productId: string } & EventOptions = { userId, productId, ...options };
    if (options.orderId !== undefined) {
      extra.order_id = options.orderId;
      args.eventId ??= deterministicId("purchase", options.orderId, options.line ?? productId, { prefix: "evt" });
    }
    return this.build("purchase", args, extra);
  }

  rating(userId: string | null, productId: string, rating: number, options: RatingOptions = {}): PreparedEvent {
    const max = options.maxRating ?? 5;
    if (!(rating >= 0 && rating <= max)) throw new InputValidationError(`rating must be between 0 and ${max}`);
    return this.build("rating", { userId, productId, ...options }, { rating, max_rating: max });
  }

  search(userId: string | null, query: string, options: EventOptions = {}): PreparedEvent {
    return this.build("search", { userId, productId: null, ...options }, { query });
  }

  addToWishlist(userId: string | null, productId: string, options: EventOptions = {}): PreparedEvent {
    return this.build("add_to_wishlist", { userId, productId, ...options });
  }
}

function cartExtra(quantity: number, options: CartOptions): JsonObject {
  const extra: JsonObject = { quantity };
  if (options.price !== undefined) extra.price = String(options.price);
  if (options.currency !== undefined) extra.currency = options.currency;
  return extra;
}
