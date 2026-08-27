import { Check, MAX_DATA_PLANE_ID, MAX_EXCLUSIONS, MAX_RECENT_EVENTS, MAX_TOP_N } from '../bounds.js';
import type { Transport } from '../transport.js';
import { instant } from '../types.js';
import type {
  CallOptions,
  CustomerRecommendationRequest,
  RecentEvent,
  RecommendationResponse,
  SessionRecommendationRequest,
} from '../types.js';

interface WireItem {
  external_product_id: string;
  rank: number;
  score: number;
  candidate_source: string;
}

interface WireResponse {
  request_id: string;
  model_version: { version_id: string; version_number: number } | null;
  strategy: string;
  fallback_applied: boolean;
  items: WireItem[];
  ordering_policy_version: number;
  latency_ms: number;
}

function wireEvents(events: RecentEvent[] | undefined): unknown[] | undefined {
  return events?.map((event) => ({
    external_product_id: event.externalProductId,
    ...(event.eventType === undefined ? {} : { event_type: event.eventType }),
    ...(event.occurredAt === undefined ? {} : { occurred_at: instant(event.occurredAt) }),
  }));
}

function decode(wire: WireResponse): RecommendationResponse {
  return {
    requestId: wire.request_id,
    modelVersion:
      wire.model_version === null
        ? null
        : {
            versionId: wire.model_version.version_id,
            versionNumber: wire.model_version.version_number,
          },
    strategy: wire.strategy,
    fallbackApplied: wire.fallback_applied,
    items: wire.items.map((item) => ({
      externalProductId: item.external_product_id,
      rank: item.rank,
      score: item.score,
      candidateSource: item.candidate_source,
    })),
    orderingPolicyVersion: wire.ordering_policy_version,
    latencyMs: wire.latency_ms,
  };
}

function checkCommon(
  check: Check,
  request: { requestId: string; topN?: number; recentEvents?: RecentEvent[]; excludeProductIds?: string[] },
): void {
  check
    .text('request_id', request.requestId, MAX_DATA_PLANE_ID)
    .int('top_n', request.topN, 1, MAX_TOP_N)
    .optionalCollection('recent_events', request.recentEvents, MAX_RECENT_EVENTS)
    .optionalCollection('exclude_product_ids', request.excludeProductIds, MAX_EXCLUSIONS);
  request.recentEvents?.forEach((event, index) => {
    check.text(`recent_events[${index}].external_product_id`, event.externalProductId, MAX_DATA_PLANE_ID);
    check.instant(`recent_events[${index}].occurred_at`, event.occurredAt, false);
  });
}

/**
 * The hot path, on the data plane.
 *
 * Both calls are retried on a transient failure, which is safe because
 * `request_id` is the idempotency key (`graphrec/domain/serving/recommend.py`
 * keys the request row on it) — so a retry after a timeout is confirmed rather
 * than counted twice, and the recommendation you eventually get is the one your
 * feedback will refer to.
 */
export class Recommendations {
  readonly #transport: Transport;

  constructor(transport: Transport) {
    this.#transport = transport;
  }

  /** Recommendations for a known customer. `sessionId` narrows it to one visit. */
  async forCustomer(
    request: CustomerRecommendationRequest,
    options?: CallOptions,
  ): Promise<RecommendationResponse> {
    const check = new Check();
    checkCommon(check, request);
    check.text('customer_id', request.customerId, MAX_DATA_PLANE_ID);
    check.text('session_id', request.sessionId, MAX_DATA_PLANE_ID, false);
    check.done('A recommendation request');

    const wire = await this.#transport.send<WireResponse>({
      method: 'POST',
      path: '/v1/recommendations',
      idempotent: true,
      ...(options === undefined ? {} : { options }),
      body: {
        request_id: request.requestId,
        customer_id: request.customerId,
        ...(request.sessionId === undefined ? {} : { session_id: request.sessionId }),
        ...(request.topN === undefined ? {} : { top_n: request.topN }),
        ...(request.recentEvents === undefined ? {} : { recent_events: wireEvents(request.recentEvents) }),
        ...(request.excludeProductIds === undefined
          ? {}
          : { exclude_product_ids: request.excludeProductIds }),
        ...(request.context === undefined ? {} : { context: request.context }),
        ...(request.allowFallback === undefined ? {} : { allow_fallback: request.allowFallback }),
      },
    });
    return decode(wire);
  }

  /** Recommendations for an anonymous visit, with no customer to name. */
  async forSession(
    request: SessionRecommendationRequest,
    options?: CallOptions,
  ): Promise<RecommendationResponse> {
    const check = new Check();
    checkCommon(check, request);
    check.text('session_id', request.sessionId, MAX_DATA_PLANE_ID);
    check.done('A session recommendation request');

    const wire = await this.#transport.send<WireResponse>({
      method: 'POST',
      path: '/v1/recommendations/session',
      idempotent: true,
      ...(options === undefined ? {} : { options }),
      body: {
        request_id: request.requestId,
        session_id: request.sessionId,
        ...(request.topN === undefined ? {} : { top_n: request.topN }),
        ...(request.recentEvents === undefined ? {} : { recent_events: wireEvents(request.recentEvents) }),
        ...(request.excludeProductIds === undefined
          ? {}
          : { exclude_product_ids: request.excludeProductIds }),
        ...(request.context === undefined ? {} : { context: request.context }),
        ...(request.allowFallback === undefined ? {} : { allow_fallback: request.allowFallback }),
      },
    });
    return decode(wire);
  }
}
