/**
 * The README's code blocks, as code.
 *
 * Every fenced block in `README.md` is a region below, and `readme.test.ts`
 * asserts the two are character-for-character identical and then runs them.
 * Documentation that is only proofread drifts; documentation that is compiled
 * against the shipped types and executed against a recorded transport cannot.
 */

import {
  GraphRec,
  QuotaExhaustedError,
  RateLimitedError,
  SubmissionFailedError,
  UnavailableError,
} from '../src/index.js';
import type { RecommendationResponse, Submission } from '../src/index.js';

export function construct(): GraphRec {
  // #region construct
  const gr = new GraphRec({
    apiKey: process.env.GRAPHREC_API_KEY!,
    tenantId: process.env.GRAPHREC_TENANT_ID!,
    domain: 'graphrec.example',
  });
  // #endregion construct
  return gr;
}

export async function recommend(gr: GraphRec): Promise<RecommendationResponse> {
  // #region recommend
  const answer = await gr.recommendations.forCustomer({
    requestId: crypto.randomUUID(),
    customerId: 'customer-1',
    topN: 10,
    recentEvents: [{ externalProductId: 'sku-1', eventType: 'view' }],
    excludeProductIds: ['sku-9'],
  });

  for (const item of answer.items) {
    console.log(item.rank, item.externalProductId, item.score);
  }
  // #endregion recommend
  return answer;
}

export async function report(gr: GraphRec, answer: RecommendationResponse): Promise<void> {
  // #region feedback
  await gr.feedback.impressions({
    requestId: answer.requestId,
    events: answer.items.map((item) => ({
      eventId: `${answer.requestId}:${item.externalProductId}`,
      externalProductId: item.externalProductId,
    })),
  });

  await gr.feedback.conversions({
    requestId: answer.requestId,
    events: [{ eventId: 'order-4471', externalProductId: 'sku-1', value: 19.99 }],
  });
  // #endregion feedback
}

export async function sync(gr: GraphRec): Promise<Submission> {
  // #region catalog
  const accepted = await gr.catalog.sync({
    syncId: '2026-08-24-nightly',
    mode: 'upsert',
    products: [
      {
        externalId: 'sku-1',
        title: 'Example product',
        category: 'example',
        price: '19.99',
        availability: 'in_stock',
      },
    ],
  });

  const finished = await gr.submissions.wait(accepted.submissionId, { timeout: 120_000 });
  console.log(finished.counts);
  // #endregion catalog
  return finished;
}

export async function ingest(gr: GraphRec): Promise<void> {
  // #region events
  const receipt = await gr.events.submit({
    eventId: '11111111-1111-4111-8111-111111111111',
    customerId: 'customer-1',
    externalProductId: 'sku-1',
    eventType: 'view',
    occurredAt: new Date(),
  });

  if (receipt.status === 'duplicate_confirmed') {
    console.log('already had it, first seen at', receipt.firstReceivedAt);
  }
  // #endregion events
}

export async function handle(gr: GraphRec): Promise<string> {
  // #region errors
  try {
    const answer = await gr.recommendations.forCustomer({
      requestId: crypto.randomUUID(),
      customerId: 'customer-1',
    });
    return answer.strategy;
  } catch (error) {
    if (error instanceof QuotaExhaustedError) {
      // Waiting will not help: the allowance resets with the billing period.
      return 'quota';
    }
    if (error instanceof RateLimitedError) {
      // The SDK already retried within your timeout budget.
      return 'rate-limited';
    }
    if (error instanceof UnavailableError) {
      // No ready model, and `allowFallback: false` was set somewhere upstream.
      return 'unavailable';
    }
    throw error;
  }
  // #endregion errors
}

export async function failed(gr: GraphRec): Promise<string[]> {
  // #region submission-errors
  try {
    await gr.submissions.wait('submission-id');
  } catch (error) {
    if (error instanceof SubmissionFailedError) {
      return error.submission.errors.map((item) => `${item.ref}: ${item.reason}`);
    }
    throw error;
  }
  return [];
  // #endregion submission-errors
}
