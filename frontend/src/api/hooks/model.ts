/**
 * Training runs and model versions — the two halves of one story.
 *
 * Every enablement decision on these pages is the server's. `can_cancel` and
 * `blocked_reason` on a job, `actions.{activate,rollback,archive}` on a version,
 * and the whole of `GET /v1/training-jobs/eligibility` are gate 5 arriving as
 * data (§10.4). Nothing in this file recomputes any of them from the state
 * field, and nothing should: the server knows about the *other* job that is
 * running, and this client does not.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import { tenantApi } from '../client';
import type { S } from '../schema';

export type TrainingJob = S['TrainingJobResponse'];
export type TrainingEligibility = S['TrainingEligibilityResponse'];
export type TrainingMetrics = S['TrainingMetricsResponse'];
export type ModelVersion = S['ModelVersionResponse'];
export type ModelVersionListItem = S['ModelVersionListItem'];
export type ModelVersionSummary = S['ModelVersionSummaryResponse'];

/** The nine stages of a successful run, in order. §7 draws these as a rail. */
export const TRAINING_STAGES = [
  'queued',
  'waiting_for_resources',
  'preparing_data',
  'building_graph',
  'training',
  'evaluating',
  'indexing_embeddings',
  'registering',
  'succeeded',
] as const;

/** The three ways out that are not the ninth stage. */
export const TERMINAL_STATES = ['succeeded', 'failed', 'cancelled'] as const;

export function isTerminal(state: string): boolean {
  return (TERMINAL_STATES as readonly string[]).includes(state);
}

// ---------------------------------------------------------------- training

export const trainingJobsQuery = (state?: string) => ({
  queryKey: ['training-jobs', state ?? null] as const,
  queryFn: () =>
    tenantApi.get<S['TrainingJobListResponse']>(
      `/v1/training-jobs${state ? `?state=${encodeURIComponent(state)}` : ''}`,
    ),
});

export const trainingEligibilityQuery = {
  queryKey: ['training-eligibility'] as const,
  queryFn: () => tenantApi.get<TrainingEligibility>('/v1/training-jobs/eligibility'),
};

/**
 * §10.8: 2 s until the job reaches a terminal state.
 *
 * The interval is a function of the cached data rather than a constant, so a
 * job that finishes between two polls stops the third. A component that
 * unmounted the interval in an effect instead would keep asking about a job
 * that settled, once per two seconds, for as long as the tab stayed open.
 */
export const trainingJobQuery = (jobId: string) => ({
  queryKey: ['training-job', jobId] as const,
  queryFn: () =>
    tenantApi.get<TrainingJob>(`/v1/training-jobs/${encodeURIComponent(jobId)}`),
  retry: false,
  refetchInterval: (result: { state: { data?: TrainingJob } }) => {
    const state = result.state.data?.state;
    return state && isTerminal(state) ? false : 2000;
  },
});

export const trainingMetricsQuery = (jobId: string) => ({
  queryKey: ['training-metrics', jobId] as const,
  queryFn: () =>
    tenantApi.get<TrainingMetrics>(
      `/v1/training-jobs/${encodeURIComponent(jobId)}/metrics`,
    ),
  retry: false,
});

export function useTrainingJob(jobId: string): UseQueryResult<TrainingJob> {
  return useQuery(trainingJobQuery(jobId));
}

export function startTraining(body: S['RequestTrainingRequest']): Promise<TrainingJob> {
  return tenantApi.post<TrainingJob>('/v1/training-jobs', body);
}

export function cancelTraining(
  jobId: string,
  body: S['CancelTrainingRequest'],
): Promise<TrainingJob> {
  return tenantApi.post<TrainingJob>(
    `/v1/training-jobs/${encodeURIComponent(jobId)}:cancel`,
    body,
  );
}

// ---------------------------------------------------------------- registry

export const modelVersionsQuery = (status?: string) => ({
  queryKey: ['model-versions', status ?? null] as const,
  queryFn: () =>
    tenantApi.get<S['ModelVersionListResponse']>(
      `/v1/model-versions${status ? `?status=${encodeURIComponent(status)}` : ''}`,
    ),
});

export const modelSummaryQuery = {
  queryKey: ['model-summary'] as const,
  queryFn: () => tenantApi.get<ModelVersionSummary>('/v1/model-versions/summary'),
};

export const modelVersionQuery = (versionId: string) => ({
  queryKey: ['model-version', versionId] as const,
  queryFn: () =>
    tenantApi.get<ModelVersion>(`/v1/model-versions/${encodeURIComponent(versionId)}`),
  retry: false,
});

export function activateVersion(
  versionId: string,
  body: S['ActivateVersionRequest'],
): Promise<ModelVersion> {
  return tenantApi.post<ModelVersion>(
    `/v1/model-versions/${encodeURIComponent(versionId)}:activate`,
    body,
  );
}

export function archiveVersion(
  versionId: string,
  body: S['ArchiveVersionRequest'],
): Promise<ModelVersion> {
  return tenantApi.post<ModelVersion>(
    `/v1/model-versions/${encodeURIComponent(versionId)}:archive`,
    body,
  );
}

export function rollbackModel(
  modelId: string,
  body: S['RollbackRequest'],
): Promise<ModelVersion> {
  return tenantApi.post<ModelVersion>(
    `/v1/models/${encodeURIComponent(modelId)}:rollback`,
    body,
  );
}

/**
 * Invalidates everything a lifecycle action can move.
 *
 * Activating a version changes that version, the previous active one, the five
 * summary counts, the deployment, and the onboarding checklist. Listing them is
 * verbose and correct; invalidating only the version acted on is short and
 * leaves the page showing two active versions.
 */
export function useModelMutation<TInput, TOutput>(action: (input: TInput) => Promise<TOutput>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      for (const key of [
        ['model-versions'],
        ['model-version'],
        ['model-summary'],
        ['deployment'],
        ['onboarding'],
      ]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
}

export function useTrainingMutation<TInput, TOutput>(
  action: (input: TInput) => Promise<TOutput>,
) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: action,
    onSuccess: () => {
      for (const key of [
        ['training-jobs'],
        ['training-job'],
        ['training-eligibility'],
        ['onboarding'],
      ]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
}
