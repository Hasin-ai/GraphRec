import { ConfigurationError } from './errors.js';

/**
 * A GraphRec API credential, holding the secret where nothing can print it.
 *
 * The credential is `gr_live_XXXX.<43 url-safe characters>`
 * (`graphrec/auth/api_keys.py`). The prefix is a **public identifier** — the
 * console prints it in the credentials table and the server logs it as the actor
 * on every request — and all 256 bits of entropy are after the separator.
 *
 * **The secret is a `#private` field, and that is the whole point of this class
 * existing rather than a string on the client object.** `JSON.stringify`,
 * `util.inspect`, a structured logger walking own properties and a crash
 * reporter serialising local variables all skip `#private` fields. A plain
 * string would appear in every one of them. This is the same reasoning as
 * `GeneratedSecret.__repr__` on the server, which is deliberately lossy for
 * exactly this failure: it is silent, so the defence belongs on the type rather
 * than in the discipline of each call site.
 *
 * **Not a request signature.** `apps/inference/deps.py` reads the credential
 * through `fastapi.security.HTTPBearer` and `apps/control_api/deps.py` does the
 * same; the HMAC-SHA-256 in `api_keys.py` hashes the secret *at rest* against a
 * server-side pepper. There is no canonical string to build, no `X-Signature`
 * and no clock-skew window, so this class has no signing method and needs none.
 */
export class Credential {
  /** `gr_live_XXXX`. Safe to log — it is how a person tells two credentials apart. */
  readonly prefix: string;

  readonly #secret: string;

  constructor(raw: string) {
    // Every message in here describes the *shape* and never quotes the value.
    // A configuration error that echoes the credential puts it in the one place
    // people paste most freely: a bug report.
    if (typeof raw !== 'string' || raw.trim() === '') {
      throw new ConfigurationError('apiKey is required and must be a non-empty string.');
    }
    const value = raw.trim();
    const separator = value.indexOf('.');
    if (separator <= 0 || separator === value.length - 1) {
      throw new ConfigurationError(
        'apiKey is not a GraphRec credential: it must be a prefix and a secret ' +
          'separated by a single "." — the whole value the console showed you once.',
      );
    }
    const prefix = value.slice(0, separator);
    if (!prefix.startsWith('gr_live_')) {
      throw new ConfigurationError(
        'apiKey does not start with "gr_live_". Check you copied the credential ' +
          'from Credentials, not the key id or the visible prefix from the table.',
      );
    }
    this.prefix = prefix;
    this.#secret = value;
  }

  /** The `Authorization` value. The only method that can see the secret. */
  get authorization(): string {
    return `Bearer ${this.#secret}`;
  }

  toString(): string {
    return `${this.prefix}.[redacted]`;
  }

  toJSON(): string {
    return this.toString();
  }

  /** `console.log(client)` in Node goes through this rather than own properties. */
  [Symbol.for('nodejs.util.inspect.custom')](): string {
    return `Credential(${this.toString()})`;
  }
}
