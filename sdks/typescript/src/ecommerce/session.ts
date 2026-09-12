/**
 * Fetch recommendations and send impression, click and conversion feedback
 * consistently. Impressions are recorded automatically and linked to later
 * clicks by `request_id`.
 *
 *     const widget = new RecommendationSession(client);
 *     const recs = await widget.recommend({ userId: "customer-42", topN: 6 });
 *     await widget.click(recs, recs.items[0].external_product_id);
 *     await widget.convert(recs, recs.items[0].external_product_id, { value: "59.00" });
 */
import type { GraphRec } from "../client.js";
import type { ClickOptions, ConversionOptions, ImpressionOptions, RecommendationOptions } from "../resources/recommendations.js";
import type { FeedbackReceipt, Recommendations } from "../types.js";

export interface RecommendOptions extends RecommendationOptions {
  /** Session-based recommendations for anonymous shoppers. */
  sessionId?: string;
  recentProductIds?: readonly string[];
}

export interface RecommendationSessionOptions {
  /** Record an impression for every non-empty result (default `true`). */
  autoImpression?: boolean;
  /** How many `request_id -> impression event_id` links to remember (default 1000). */
  remember?: number;
}

/** Bounded insertion-ordered map. */
class ImpressionIndex {
  private readonly data = new Map<string, string>();
  constructor(private readonly capacity: number) {}
  put(requestId: string, eventId: string): void {
    this.data.delete(requestId);
    this.data.set(requestId, eventId);
    while (this.data.size > this.capacity) {
      const oldest = this.data.keys().next().value;
      if (oldest === undefined) break;
      this.data.delete(oldest);
    }
  }
  get(requestId: string): string | undefined {
    return this.data.get(requestId);
  }
}

export class RecommendationSession {
  readonly autoImpression: boolean;
  private readonly impressions: ImpressionIndex;

  constructor(private readonly client: GraphRec, options: RecommendationSessionOptions = {}) {
    this.autoImpression = options.autoImpression ?? true;
    this.impressions = new ImpressionIndex(Math.max(1, options.remember ?? 1000));
  }

  /** Personalized results for `userId`, or session-based when `sessionId` is given. */
  async recommend(options: RecommendOptions = {}): Promise<Recommendations> {
    const { sessionId, recentProductIds, ...rest } = options;
    const recs = sessionId !== undefined ? await this.client.recommendations.forSession({ ...rest, sessionId, recentProductIds }) : await this.client.recommendations.get(rest);
    if (this.autoImpression && recs.items.length) await this.impression(recs);
    return recs;
  }

  async impression(recs: Recommendations, options: ImpressionOptions = {}): Promise<FeedbackReceipt> {
    const receipt = await this.client.feedback.impression(recs, options);
    this.impressions.put(recs.request_id, receipt.event_id);
    return receipt;
  }

  async click(recs: Recommendations, productId: string, options: ClickOptions = {}): Promise<FeedbackReceipt> {
    return this.client.feedback.click(recs, productId, { impressionEventId: this.impressions.get(recs.request_id), ...options });
  }

  async convert(recs: Recommendations, productId: string, options: ConversionOptions = {}): Promise<FeedbackReceipt> {
    return this.client.feedback.conversion(recs, productId, options);
  }
}
