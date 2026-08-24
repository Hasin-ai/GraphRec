/**
 * Interaction events: the single-event route and the batch route.
 *
 * Both live here rather than in `catalogue.ts` because they are the other half
 * of ingestion — the catalogue says what exists, events say what happened to
 * it — and because the console's events page submits both shapes from one
 * form.
 */

import { tenantApi } from '../client';
import type { S } from '../schema';
import type { Submission } from './catalogue';

export type EventResult = S['SubmitEventResponse'];

export function submitEvent(body: S['SubmitEventRequest']): Promise<EventResult> {
  return tenantApi.post<EventResult>('/v1/events', body);
}

export function submitEventBatch(body: S['SubmitEventBatchRequest']): Promise<Submission> {
  return tenantApi.post<Submission>('/v1/events/batches', body);
}
