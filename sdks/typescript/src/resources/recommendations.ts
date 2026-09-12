import { MAX_EXCLUSIONS, MAX_TOP_N } from "../constants.js";
import { InputValidationError } from "../errors.js";
import { newId } from "../ids.js";
import type { FeedbackReceipt, JsonObject, Money, RecommendationItem, Recommendations } from "../types.js";
import { Resource, toIso, utcNow } from "./base.js";

export interface RecommendationOptions {
  userId?: string | null;
  topN?: number;
  context?: JsonObject;
  /** Items to leave out, e.g. the product on the current page or the cart contents (max 200). */
  excludeProductIds?: readonly string[];
}

export interface SessionRecommendationOptions extends RecommendationOptions {
  sessionId: string;
  /** Products viewed in this session, most recent last. Sent in `context`. */
  recentProductIds?: readonly string[];
}

/** Either the `Recommendations` object or a bare `request_id`. */
export type RecommendationRef = Recommendations | string;

export interface FeedbackOptions {
  eventId?: string;
  occurredAt?: string | Date;
  context?: JsonObject;
}

export interface ImpressionOptions extends FeedbackOptions {
  /** Required when `ref` is a bare request id: product ids in display order, or items with positions. */
  items?: readonly (string | RecommendationItem)[];
}

export interface ClickOptions extends FeedbackOptions {
  /** One-based position; derived from the `Recommendations` object when omitted. */
  position?: number;
  impressionEventId?: string;
}

export interface ConversionOptions extends FeedbackOptions {
  position?: number;
  value?: Money;
}

function requestBody(options: RecommendationOptions, session?: JsonObject): Record<string, unknown> {
  const topN = options.topN ?? 10;
  if (!Number.isInteger(topN) || topN < 1 || topN > MAX_TOP_N) throw new InputValidationError(`topN must be an integer between 1 and ${MAX_TOP_N}`);
  const body: Record<string, unknown> = { top_n: topN, context: { ...(options.context ?? {}), ...(session ?? {}) } };
  if (options.userId !== undefined && options.userId !== null) body.user_id = options.userId;
  if (options.excludeProductIds?.length) {
    const unique = Array.from(new Set(options.excludeProductIds.map(String)));
    if (unique.length > MAX_EXCLUSIONS) throw new InputValidationError(`At most ${MAX_EXCLUSIONS} product IDs can be excluded`);
    body.exclude_product_ids = unique;
  }
  return body;
}

function requestId(ref: RecommendationRef): string {
  const id = typeof ref === "string" ? ref : ref?.request_id;
  if (!id) throw new InputValidationError("A recommendation request_id is required for feedback");
  return id;
}

function normaliseItems(ref: RecommendationRef, items?: readonly (string | RecommendationItem)[]): RecommendationItem[] {
  if (items === undefined) {
    if (typeof ref === "string") throw new InputValidationError("Pass the Recommendations object, or items=[...] together with a request_id");
    return ref.items.map((i) => ({ external_product_id: i.external_product_id, position: i.position }));
  }
  return items.map((item, index) =>
    typeof item === "string" ? { external_product_id: item, position: index + 1 } : { external_product_id: String(item.external_product_id), position: Number(item.position) },
  );
}

/** One-based position of `productId` within a recommendation result, or `undefined`. */
export function positionOf(recs: Recommendations, productId: string): number | undefined {
  return recs.items.find((i) => i.external_product_id === productId)?.position;
}

function position(ref: RecommendationRef, productId: string, given: number | undefined, required: boolean): number | undefined {
  if (given !== undefined) {
    if (!Number.isInteger(given) || given < 1) throw new InputValidationError("position is one-based and must be >= 1");
    return given;
  }
  if (typeof ref !== "string") {
    const found = positionOf(ref, productId);
    if (found === undefined) throw new InputValidationError(`Product ${JSON.stringify(productId)} is not part of recommendation ${JSON.stringify(ref.request_id)}`);
    return found;
  }
  if (required) throw new InputValidationError("position is required when passing a request_id string");
  return undefined;
}

function feedbackBody(ref: RecommendationRef, options: FeedbackOptions, fields: Record<string, unknown>): Record<string, unknown> {
  const body: Record<string, unknown> = {
    event_id: options.eventId ?? newId("fbk"),
    request_id: requestId(ref),
    context: { ...(options.context ?? {}) },
    occurred_at: toIso(options.occurredAt) ?? utcNow(),
  };
  for (const [key, value] of Object.entries(fields)) if (value !== undefined && value !== null) body[key] = value;
  return body;
}

export class RecommendationsResource extends Resource {
  /**
   * Recommendations for an identified customer (`POST /v1/recommendations`).
   * Check `fallback_used` to know whether the result is personalized.
   */
  async get(options: RecommendationOptions = {}): Promise<Recommendations> {
    return this.client.request<Recommendations>("recommendations.get", { json: requestBody(options) });
  }

  /** Session-aware recommendations for anonymous shoppers (`POST /v1/recommendations/session`). */
  async forSession(options: SessionRecommendationOptions): Promise<Recommendations> {
    if (!options.sessionId) throw new InputValidationError("sessionId must be a non-empty string");
    const session: JsonObject = { session_id: options.sessionId };
    if (options.recentProductIds?.length) session.recent_product_ids = options.recentProductIds.map(String);
    return this.client.request<Recommendations>("recommendations.for_session", { json: requestBody(options, session) });
  }
}

/** Impression, click and conversion feedback. Every call is deduplicated by `event_id`. */
export class Feedback extends Resource {
  /** Report that recommendations were shown (`POST /v1/feedback/impressions`). */
  async impression(ref: RecommendationRef, options: ImpressionOptions = {}): Promise<FeedbackReceipt> {
    return this.client.request<FeedbackReceipt>("feedback.impression", { json: feedbackBody(ref, options, { items: normaliseItems(ref, options.items) }) });
  }

  /** Report a click on a recommended product (`POST /v1/feedback/clicks`). */
  async click(ref: RecommendationRef, productId: string, options: ClickOptions = {}): Promise<FeedbackReceipt> {
    return this.client.request<FeedbackReceipt>("feedback.click", {
      json: feedbackBody(ref, options, {
        external_product_id: productId,
        position: position(ref, productId, options.position, true),
        impression_event_id: options.impressionEventId,
      }),
    });
  }

  /** Report a purchase attributed to a recommendation (`POST /v1/feedback/conversions`). */
  async conversion(ref: RecommendationRef, productId: string, options: ConversionOptions = {}): Promise<FeedbackReceipt> {
    let value: string | undefined;
    if (options.value !== undefined) {
      if (!Number.isFinite(Number(options.value)) || Number(options.value) < 0) throw new InputValidationError("value must be a non-negative amount");
      value = String(options.value);
    }
    return this.client.request<FeedbackReceipt>("feedback.conversion", {
      json: feedbackBody(ref, options, {
        external_product_id: productId,
        position: position(ref, productId, options.position, false),
        value,
      }),
    });
  }
}
