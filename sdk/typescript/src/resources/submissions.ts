import { GraphRecError } from '../errors.js';
import type { Transport } from '../transport.js';
import type { CallOptions, Submission } from '../types.js';

interface WireSubmission {
  submission_id: string;
  kind: Submission['kind'];
  status: Submission['status'];
  stage: Submission['stage'];
  reference: string;
  counts: Submission['counts'];
  errors: Submission['errors'];
  error_count: number;
  failure_code: string | null;
  submitted_at: string;
  completed_at: string | null;
}

export function decodeSubmission(wire: WireSubmission): Submission {
  return {
    submissionId: wire.submission_id,
    kind: wire.kind,
    status: wire.status,
    stage: wire.stage,
    reference: wire.reference,
    counts: wire.counts,
    errors: wire.errors,
    errorCount: wire.error_count,
    failureCode: wire.failure_code,
    submittedAt: wire.submitted_at,
    completedAt: wire.completed_at,
  };
}

export type { WireSubmission };

/**
 * `wait` gave up before the submission reached a terminal state.
 *
 * Carries the last state it saw, so the caller can keep polling with their own
 * scheduler instead of starting over. A bare timeout would throw away the one
 * thing that makes resuming possible.
 */
export class SubmissionTimeoutError extends GraphRecError {
  readonly submission: Submission;

  constructor(submission: Submission, waited: number) {
    super(
      `Submission ${submission.submissionId} was still ${submission.stage} after ${waited}ms. ` +
        'It has not failed — poll it again with `submissions.get`.',
      {
        code: 'submission_not_ready',
        errorClass: 'unavailable',
        reason: 'The submission has not finished yet.',
        reference: null,
        retryable: true,
      },
    );
    this.submission = submission;
  }
}

/**
 * The submission finished and its verdict is `failed`.
 *
 * Thrown by `wait` only. `get` returns a failed submission as a value, because
 * asking how a batch went and being told "badly" is a successful call.
 */
export class SubmissionFailedError extends GraphRecError {
  readonly submission: Submission;

  constructor(submission: Submission) {
    super(
      `Submission ${submission.submissionId} failed` +
        (submission.failureCode ? ` (${submission.failureCode})` : '') +
        `: ${submission.counts.failed} of ${submission.counts.received} item(s) were rejected.`,
      {
        code: submission.failureCode ?? 'submission_failed',
        errorClass: 'validation',
        reason: 'The submission failed.',
        reference: submission.reference,
        fieldErrors: submission.errors.map((error) => ({ field: error.ref, reason: error.reason })),
      },
    );
    this.submission = submission;
  }
}

/** Poll cadence: gentle at first because most submissions finish quickly. */
const FIRST_POLL_MS = 500;
const POLL_FACTOR = 1.5;
const MAX_POLL_MS = 5_000;
const DEFAULT_WAIT_MS = 60_000;

export interface WaitOptions extends CallOptions {
  /** Total budget for the wait, not for one poll. Default 60000. */
  timeout?: number;
}

/**
 * Reading a submission, and the loop every integration otherwise writes itself.
 *
 * Bulk upsert and event batches answer `202` with a submission that is
 * `processing`: the work happens in the job worker and the counts arrive later.
 * So every customer writes a poll, and the interesting part is that most of them
 * write the same three bugs — a fixed interval that hammers the API, no ceiling
 * so a stuck job spins forever, and treating `failed` as an exception without
 * keeping the per-item `errors` that say what to fix. `wait` is here so that
 * loop is written once.
 *
 * A submission is addressable by its id or by the identifier you chose, and by
 * nothing else — there is no submission index
 * (`apps/control_api/routers/ingestion.py`), which is why this class has no
 * `list`.
 */
export class Submissions {
  readonly #transport: Transport;

  constructor(transport: Transport) {
    this.#transport = transport;
  }

  /** By submission id, as returned from `catalog.sync` or `events.submitBatch`. */
  async get(submissionId: string, options?: CallOptions): Promise<Submission> {
    const wire = await this.#transport.send<WireSubmission>({
      method: 'GET',
      path: `/v1/submissions/${encodeURIComponent(submissionId)}`,
      idempotent: true,
      ...(options === undefined ? {} : { options }),
    });
    return decodeSubmission(wire);
  }

  /**
   * By the `batchId` you chose.
   *
   * The reason this exists: if the `202` never reached you, you do not have a
   * submission id — but you do have the identifier you sent, and that is enough
   * to find out whether the batch landed. Without it, a timeout on submit leaves
   * an integration with no way to ask.
   */
  async getBatch(batchId: string, options?: CallOptions): Promise<Submission> {
    const wire = await this.#transport.send<WireSubmission>({
      method: 'GET',
      path: `/v1/events/batches/${encodeURIComponent(batchId)}`,
      idempotent: true,
      ...(options === undefined ? {} : { options }),
    });
    return decodeSubmission(wire);
  }

  /**
   * Poll until the submission is terminal.
   *
   * Resolves on `succeeded`, throws `SubmissionFailedError` on `failed` with the
   * per-item reasons attached, and throws `SubmissionTimeoutError` carrying the
   * last state when the budget runs out.
   */
  async wait(submissionId: string, options?: WaitOptions): Promise<Submission> {
    const budget = options?.timeout ?? DEFAULT_WAIT_MS;
    const deadline = Date.now() + budget;
    let interval = FIRST_POLL_MS;
    let latest: Submission;

    for (;;) {
      // Each poll gets what remains, so the wait is one budget rather than a
      // budget per request multiplied by an unbounded number of requests.
      const remaining = deadline - Date.now();
      latest = await this.get(submissionId, {
        ...(options?.signal === undefined ? {} : { signal: options.signal }),
        ...(options?.requestId === undefined ? {} : { requestId: options.requestId }),
        timeout: Math.max(remaining, 1),
      });

      if (latest.status === 'succeeded') return latest;
      if (latest.status === 'failed') throw new SubmissionFailedError(latest);

      const wait = Math.min(interval, deadline - Date.now());
      if (wait <= 0) throw new SubmissionTimeoutError(latest, budget);
      await new Promise((resolve) => setTimeout(resolve, wait));
      interval = Math.min(Math.floor(interval * POLL_FACTOR), MAX_POLL_MS);
    }
  }
}
