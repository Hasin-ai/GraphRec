import type { ResolvedConfig } from './config.js';
import {
  GraphRecError,
  TimeoutError,
  TransportError,
  errorFrom,
} from './errors.js';
import type { CallOptions } from './types.js';

export interface RequestSpec {
  method: 'GET' | 'POST';
  path: string;
  body?: unknown;
  /**
   * Whether re-sending this exact request is safe.
   *
   * True only when the payload carries the deduplicating identifier the route
   * keys on — `event_id`, `sync_id`, `batch_id`, `request_id`. This is a
   * property of the *call site*, not of the method: a POST is idempotent here
   * and a hypothetical one without a key would not be.
   */
  idempotent: boolean;
  options?: CallOptions;
}

/** Full jitter, base 250 ms, doubling, capped at 8 s. */
const BASE_DELAY_MS = 250;
const MAX_DELAY_MS = 8_000;

function backoff(attempt: number, random: () => number): number {
  return Math.floor(random() * Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** attempt));
}

/**
 * `setTimeout`, cancellable.
 *
 * Rejects with `signal.reason` verbatim — the `AbortError` the platform made,
 * or whatever the caller passed to `abort()`. `reason` is typed `any`, hence
 * the assertion: substituting an `Error` of our own here would replace the
 * caller's cancellation with a lookalike and break `error.name === 'AbortError'`
 * in their code, which is the one check everybody writes.
 */
const sleep = (ms: number, signal?: AbortSignal): Promise<void> =>
  new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason as Error);
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(signal?.reason as Error);
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });

/**
 * One host, one credential, and the retry policy.
 *
 * There is a `Transport` per plane and each namespace on the client holds
 * exactly one, which is what makes "send a data-plane call to the control host"
 * unrepresentable rather than merely documented.
 *
 * **Retrying asks two questions and needs both answered yes.** Is the failure
 * transient — `GraphRecError.isTransient`, which is the server's own verdict
 * rather than a status-code table maintained here. And is the call idempotent —
 * `RequestSpec.idempotent`, which is true only when the caller supplied the key
 * the route deduplicates on. A retry that changed the key would not be a retry;
 * it would be a second submission, which is exactly the failure this SDK refuses
 * to generate identifiers in order to avoid.
 *
 * **The budget is a deadline, not an attempt count.** `timeout` bounds the whole
 * call including sleeps, so a recommendation on a hot path with a 200 ms budget
 * does not spend two seconds backing off behind the caller's back. Attempts stop
 * when the next delay would not fit.
 */
export class Transport {
  readonly origin: string;
  readonly #config: ResolvedConfig;
  readonly #random: () => number;

  constructor(origin: string, config: ResolvedConfig, random: () => number = Math.random) {
    this.origin = origin;
    this.#config = config;
    this.#random = random;
  }

  async send<T>(spec: RequestSpec): Promise<T> {
    const budget = spec.options?.timeout ?? this.#config.timeout;
    const deadline = Date.now() + budget;
    const caller = spec.options?.signal;

    const headers: Record<string, string> = {
      // The whole of the credential contract on the wire. Not a signature —
      // `HTTPBearer` on both apps reads this value and nothing else.
      Authorization: this.#config.credential.authorization,
      Accept: 'application/json',
      'User-Agent': this.#config.userAgent,
    };
    if (spec.body !== undefined) headers['Content-Type'] = 'application/json';
    if (spec.options?.requestId) headers['X-Request-Id'] = spec.options.requestId;

    const payload = spec.body === undefined ? undefined : JSON.stringify(spec.body);
    const url = `${this.origin}${spec.path}`;

    let lastError: GraphRecError | undefined;

    for (let attempt = 0; ; attempt += 1) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) {
        throw lastError ?? new TimeoutError(`No time left in the ${budget}ms budget for ${spec.path}.`);
      }

      let response: Response;
      try {
        response = await this.#config.fetch(url, {
          method: spec.method,
          headers,
          body: payload,
          signal: this.#signal(caller, remaining),
        });
      } catch (cause) {
        if (caller?.aborted) throw cause;
        if (Date.now() >= deadline) {
          throw new TimeoutError(
            `${spec.method} ${spec.path} did not complete within ${budget}ms.`,
          );
        }
        // DNS, connect, TLS, socket. Both edges pin `protocols tls1.3`, so a
        // runtime that cannot negotiate it lands here with no status to look up.
        lastError = new TransportError(
          `${spec.method} ${spec.path} could not reach ${this.origin}. ` +
            'Check network reachability, and that this runtime can negotiate TLS 1.3 — ' +
            'both GraphRec edges require it.',
          cause,
        );
        if (!this.#willRetry(attempt, spec, lastError, deadline)) throw lastError;
        await this.#wait(attempt, lastError, deadline, caller);
        continue;
      }

      const requestId = response.headers.get('X-Request-Id');
      const parsed = await this.#read(response);

      if (response.ok) return parsed as T;

      lastError = errorFrom(response.status, parsed, requestId);
      if (!this.#willRetry(attempt, spec, lastError, deadline)) throw lastError;
      await this.#wait(attempt, lastError, deadline, caller);
    }
  }

  /** The caller's cancellation and our deadline, whichever fires first. */
  #signal(caller: AbortSignal | undefined, remaining: number): AbortSignal {
    const budgeted = AbortSignal.timeout(remaining);
    return caller ? AbortSignal.any([caller, budgeted]) : budgeted;
  }

  #willRetry(attempt: number, spec: RequestSpec, error: GraphRecError, deadline: number): boolean {
    if (!spec.idempotent) return false;
    if (attempt >= this.#config.maxRetries) return false;
    if (!error.isTransient) return false;
    return this.#delay(attempt, error) + Date.now() < deadline;
  }

  /** `Retry-After` when the server named one; otherwise jittered backoff. */
  #delay(attempt: number, error: GraphRecError): number {
    return error.retryAfterSeconds !== null
      ? error.retryAfterSeconds * 1_000
      : backoff(attempt, this.#random);
  }

  async #wait(
    attempt: number,
    error: GraphRecError,
    deadline: number,
    caller: AbortSignal | undefined,
  ): Promise<void> {
    const delay = Math.min(this.#delay(attempt, error), deadline - Date.now());
    if (delay > 0) await sleep(delay, caller);
  }

  /**
   * The body, or `undefined` when there is not one to read.
   *
   * A non-JSON body is not an exception here. A 502 from a proxy that never
   * reached the application is HTML, and turning that into a parse error would
   * lose the status — which is the only information the response carried.
   * `errorFrom` handles the shapeless case.
   */
  async #read(response: Response): Promise<unknown> {
    const text = await response.text();
    if (text === '') return undefined;
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return undefined;
    }
  }
}
