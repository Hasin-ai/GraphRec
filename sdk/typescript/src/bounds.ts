import { ValidationError } from './errors.js';
import type { FieldError } from './errors.js';

/**
 * The published bounds, checked here so they fail at the caller's desk.
 *
 * Each constant names where the server's copy lives. They are the defaults of a
 * standard estate — several are settings (`recommendation_max_top_n`,
 * `max_products_per_sync`) and a self-hosted deployment could raise them — which
 * is why nothing here invents a bound the schema does not publish, and why the
 * checks are cheap and structural rather than a second validation layer. The
 * server remains the authority; this only shortens the loop on the mistakes that
 * are certain.
 *
 * The two planes do **not** agree on identifier length, and that is not an
 * oversight to smooth over. The data plane takes `maxLength: 200`
 * (`frontend/openapi.json`); a bulk ingestion item is refused above 120
 * (`MAX_EXTERNAL_ID_LENGTH`, `graphrec/domain/ingestion/validation.py`), which
 * matches the `ck_*_external_id_length` constraints in migrations 0007 and 0008.
 * A single shared constant would have to be one of the two and would be wrong
 * about the other.
 */

/** `frontend/openapi.json` — `request_id`, `customer_id`, `session_id`, feedback ids. */
export const MAX_DATA_PLANE_ID = 200;
/** `graphrec/domain/ingestion/validation.py` — and the DB check constraints. */
export const MAX_EXTERNAL_ID = 120;
export const MAX_TITLE = 500;
export const MAX_CATEGORY = 120;
export const MAX_DESCRIPTION = 4_000;

/** `recommendation_max_top_n`, `recommendation_max_recent_events`, `..._exclusions`. */
export const MAX_TOP_N = 100;
export const MAX_RECENT_EVENTS = 50;
export const MAX_EXCLUSIONS = 200;

/** `max_products_per_sync`, `max_events_per_batch`. */
export const MAX_PRODUCTS_PER_SYNC = 5_000;
export const MAX_EVENTS_PER_BATCH = 5_000;

/**
 * Collects field failures and raises the same `ValidationError` the server
 * would, so a caller's `catch` handles a local and a remote rejection with one
 * branch. `reference` is null: no request was made, so nothing assigned one.
 */
export class Check {
  readonly #errors: FieldError[] = [];

  text(field: string, value: unknown, max: number, required = true): this {
    if (value === undefined || value === null) {
      if (required) this.#errors.push({ field, reason: 'is required' });
      return this;
    }
    if (typeof value !== 'string' || value.trim() === '') {
      this.#errors.push({ field, reason: 'must be a non-empty string' });
    } else if (value.length > max) {
      this.#errors.push({ field, reason: `must be at most ${max} characters` });
    }
    return this;
  }

  int(field: string, value: unknown, min: number, max: number): this {
    if (value === undefined) return this;
    if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) {
      this.#errors.push({ field, reason: `must be an integer between ${min} and ${max}` });
    }
    return this;
  }

  collection(field: string, value: unknown, max: number, minimum = 1): this {
    if (!Array.isArray(value)) {
      this.#errors.push({ field, reason: 'must be an array' });
    } else if (value.length < minimum) {
      this.#errors.push({ field, reason: `must contain at least ${minimum} item(s)` });
    } else if (value.length > max) {
      this.#errors.push({ field, reason: `must contain at most ${max} items` });
    }
    return this;
  }

  optionalCollection(field: string, value: unknown, max: number): this {
    if (value === undefined) return this;
    return this.collection(field, value, max, 0);
  }

  enum<T extends string>(field: string, value: unknown, allowed: readonly T[]): this {
    if (value === undefined) return this;
    if (typeof value !== 'string' || !allowed.includes(value as T)) {
      this.#errors.push({ field, reason: `must be one of: ${allowed.join(', ')}` });
    }
    return this;
  }

  /**
   * A timestamp that carries an offset.
   *
   * `parse_timestamp` refuses a naive one rather than assuming UTC, so this is
   * the check most worth doing locally: the server's refusal arrives per item,
   * inside a submission, minutes after the batch was accepted.
   */
  instant(field: string, value: unknown, required = true): this {
    if (value === undefined || value === null) {
      if (required) this.#errors.push({ field, reason: 'is required' });
      return this;
    }
    if (value instanceof Date) {
      if (Number.isNaN(value.getTime())) this.#errors.push({ field, reason: 'is an invalid Date' });
      return this;
    }
    if (typeof value !== 'string' || !/(?:Z|[+-]\d{2}:?\d{2})$/.test(value.trim())) {
      this.#errors.push({
        field,
        reason: 'must be a Date, or an RFC 3339 string carrying an offset (e.g. …T10:00:00Z)',
      });
    }
    return this;
  }

  done(what: string): void {
    if (this.#errors.length === 0) return;
    throw new ValidationError(`${what} is not valid: ${this.#errors[0]?.field} ${this.#errors[0]?.reason}.`, {
      code: 'invalid_request',
      errorClass: 'validation',
      reason: `${what} is not valid.`,
      reference: null,
      fieldErrors: this.#errors,
    });
  }
}
