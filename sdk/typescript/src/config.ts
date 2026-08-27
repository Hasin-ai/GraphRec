import { Credential } from './credential.js';
import { ConfigurationError } from './errors.js';

/**
 * Where the two hosts come from, and why there are two.
 *
 * GraphRec publishes two ports (`BACKEND_PLAN` §9.1): N1 answers the control
 * plane on one hostname shared by every tenant, and N3 answers the data plane on
 * a hostname **per tenant**. N3's edge resolves the upstream from the subdomain —
 * `graphrec-serve-{http.request.host.labels.3}-inference`,
 * `deploy/n3/Caddyfile` — and the label it reads is the tenant's UUID in hex
 * without dashes, the same value `graphrec/serving_driver/compose.py` uses as its
 * Compose project name.
 *
 * So a single `baseUrl` is not merely inelegant, it is wrong, and wrong in the
 * quietest way available: `POST https://api.example/v1/recommendations` is a 404
 * with nothing in the body to explain it, because that route does not exist on
 * that application. Nothing in this SDK's surface lets a caller choose a host —
 * each namespace is bound to one at construction.
 */
export interface GraphRecOptions {
  /** `gr_live_XXXX.<secret>`, shown once at creation and never again. */
  apiKey: string;
  /** The tenant's UUID. Dashed or hex; the console shows dashed, the hostname needs hex. */
  tenantId: string;

  /**
   * Shorthand for a standard estate: `api.<domain>` and `<hex>.serve.<domain>`,
   * which is the convention the console's /integration page publishes.
   */
  domain?: string;
  /** `GRAPHREC_CONSOLE_DOMAIN` — N1's hostname, e.g. `api.graphrec.example`. */
  consoleDomain?: string;
  /** `GRAPHREC_API_DOMAIN` — N3's base, e.g. `serve.graphrec.example`. */
  apiDomain?: string;
  /** Full origin override for the control plane. For a local stack or a test. */
  controlUrl?: string;
  /** Full origin override for the data plane, tenant subdomain included. */
  dataUrl?: string;

  /** Budget in ms for a whole call including retries. Default 10000. */
  timeout?: number;
  /** Extra attempts after the first, for idempotent calls only. Default 2. */
  maxRetries?: number;
  /** Injected for tests and for runtimes with a preconfigured agent. */
  fetch?: typeof globalThis.fetch;
  /** Appended to the SDK's own, so an estate can identify a caller in its logs. */
  userAgent?: string;
}

export interface ResolvedConfig {
  credential: Credential;
  tenantHex: string;
  controlOrigin: string;
  dataOrigin: string;
  timeout: number;
  maxRetries: number;
  fetch: typeof globalThis.fetch;
  userAgent: string;
}

const UUID = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;

/**
 * A tenant id in the form the data-plane hostname needs.
 *
 * The console shows the dashed UUID and the hostname takes the hex. A customer
 * copying from one into the other gets a host that does not resolve and an error
 * from their DNS resolver rather than from us, so both forms are accepted here
 * and normalised in one place.
 */
export function normaliseTenantId(raw: string): string {
  if (typeof raw !== 'string' || !UUID.test(raw.trim())) {
    throw new ConfigurationError(
      'tenantId must be the tenant UUID shown on the console’s Tenant page, ' +
        'dashed or as 32 hex characters.',
    );
  }
  return raw.trim().replaceAll('-', '').toLowerCase();
}

function origin(url: string, field: string): string {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new ConfigurationError(`${field} must be an absolute URL, e.g. https://api.example.com`);
  }
  if (parsed.protocol !== 'https:' && parsed.hostname !== 'localhost' && parsed.hostname !== '127.0.0.1') {
    // Not a style rule. The credential is a bearer token with no origin binding
    // and no proof-of-possession: on http it is readable by anything on the
    // path, and it is valid until somebody revokes it.
    throw new ConfigurationError(
      `${field} must be https. A GraphRec credential is a bearer token and plaintext ` +
        'transport gives it away to everything between you and the server.',
    );
  }
  return parsed.origin;
}

/**
 * Resolve both hosts. Explicit URL beats explicit domain beats the shorthand.
 *
 * Each layer has a real caller: `controlUrl`/`dataUrl` for a local stack on a
 * port, `consoleDomain`/`apiDomain` for a self-hosted estate that names its two
 * hosts independently — which is how the deploy is actually parameterised, as
 * `GRAPHREC_CONSOLE_DOMAIN` and `GRAPHREC_API_DOMAIN` — and `domain` for the
 * common case where they follow the published convention.
 */
export function resolveConfig(options: GraphRecOptions): ResolvedConfig {
  const tenantHex = normaliseTenantId(options.tenantId);

  const consoleDomain = options.consoleDomain ?? (options.domain ? `api.${options.domain}` : undefined);
  const apiDomain = options.apiDomain ?? (options.domain ? `serve.${options.domain}` : undefined);

  const controlOrigin = options.controlUrl
    ? origin(options.controlUrl, 'controlUrl')
    : consoleDomain
      ? origin(`https://${consoleDomain}`, 'consoleDomain')
      : null;
  const dataOrigin = options.dataUrl
    ? origin(options.dataUrl, 'dataUrl')
    : apiDomain
      ? origin(`https://${tenantHex}.${apiDomain}`, 'apiDomain')
      : null;

  if (controlOrigin === null || dataOrigin === null) {
    throw new ConfigurationError(
      'Both hosts must be resolvable: pass `domain`, or `consoleDomain` and `apiDomain`, ' +
        'or `controlUrl` and `dataUrl`. There are two public hosts and the data plane ' +
        'is reached on a hostname that contains your tenant id.',
    );
  }

  const timeout = options.timeout ?? 10_000;
  const maxRetries = options.maxRetries ?? 2;
  if (!Number.isFinite(timeout) || timeout <= 0) {
    throw new ConfigurationError('timeout must be a positive number of milliseconds.');
  }
  if (!Number.isInteger(maxRetries) || maxRetries < 0) {
    throw new ConfigurationError('maxRetries must be a non-negative integer.');
  }

  const fetchImpl = options.fetch ?? globalThis.fetch;
  if (typeof fetchImpl !== 'function') {
    throw new ConfigurationError(
      'No fetch implementation. Node 20 or newer provides one; on an older runtime ' +
        'pass `fetch` explicitly. Note that both GraphRec edges pin TLS 1.3.',
    );
  }

  const base = `graphrec-node/${VERSION}`;
  return {
    credential: new Credential(options.apiKey),
    tenantHex,
    controlOrigin,
    dataOrigin,
    timeout,
    maxRetries,
    fetch: fetchImpl,
    userAgent: options.userAgent ? `${base} ${options.userAgent}` : base,
  };
}

/** Kept in one place so the `User-Agent` and the package cannot disagree. */
export const VERSION = '0.1.0';
