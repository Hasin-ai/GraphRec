import { encodeJson } from "./batching.js";
import {
  API_KEY_PREFIX,
  DEFAULT_BASE_URL,
  DEFAULT_MAX_BATCH_ITEMS,
  DEFAULT_MAX_BODY_BYTES,
  DEFAULT_TIMEOUT_MS,
  ENV_ACCESS_TOKEN,
  ENV_API_KEY,
  ENV_BASE_URL,
  HEADER_CORRELATION_ID,
  HEADER_IDEMPOTENCY_KEY,
  TOKEN_EXPIRY_SKEW_SECONDS,
} from "./constants.js";
import {
  APIConnectionError,
  APIResponseValidationError,
  APITimeoutError,
  ConfigurationError,
  TokenExpiredError,
  errorFromResponse,
  type RequestInfoSummary,
} from "./errors.js";
import { RetryPolicy, sleep, type RetryOptions } from "./retry.js";
import { ApiKeys } from "./resources/apiKeys.js";
import { Auth, Tenants } from "./resources/auth.js";
import { Subscription, Usage } from "./resources/billing.js";
import { Datasets } from "./resources/datasets.js";
import { Events } from "./resources/events.js";
import { ModelVersions, TrainingJobs } from "./resources/ml.js";
import { Platform } from "./resources/platform.js";
import { Products } from "./resources/products.js";
import { Feedback, RecommendationsResource } from "./resources/recommendations.js";
import { Deployment, Metrics } from "./resources/serving.js";
import { buildPath, isPlatformRoute, route, type Route } from "./routes.js";
import type { HealthStatus, TokenPair } from "./types.js";
import { VERSION } from "./version.js";

export interface GraphRecOptions {
  /** API origin, e.g. `https://api.graphrec.example`. Defaults to `GRAPHREC_BASE_URL` or `http://localhost:8010`. */
  baseUrl?: string;
  /** Integration credential (`gr_live_…`). Sent as `Authorization: ApiKey …`. */
  apiKey?: string;
  /** A user access token you manage yourself. Sent as `Authorization: Bearer …`. */
  accessToken?: string;
  /** Console user credentials: the SDK logs in on first use and again before the token expires. */
  email?: string;
  password?: string;
  /** The server's shared `PLATFORM_ADMIN_TOKEN`, for `client.platform` only. */
  platformToken?: string;
  /** Read `GRAPHREC_*` environment variables for missing options (default `true`). */
  useEnv?: boolean;
  timeoutMs?: number;
  retry?: RetryOptions;
  /** Mirrors the server's `MAX_REQUEST_BODY_BYTES`; bulk helpers split payloads to fit. */
  maxBodyBytes?: number;
  maxBatchItems?: number;
  /** Extra headers sent with every request. */
  defaultHeaders?: Record<string, string>;
  /** Custom `fetch` (tests, proxies, polyfills). */
  fetch?: typeof fetch;
}

export interface RequestOptions {
  params?: Record<string, string | number>;
  json?: unknown;
  multipart?: FormData;
  idempotencyKey?: string;
  headers?: Record<string, string>;
  /** Override the route's default correlation id. */
  correlationId?: string;
}

interface PasswordSession {
  token: TokenPair;
  expiresAt: number;
}

function envVar(name: string): string | undefined {
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
  const value = env?.[name];
  return value && value.trim() ? value.trim() : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/**
 * The GraphRec client. One instance per credential; resources hang off it:
 *
 *     const client = new GraphRec({ apiKey: "gr_live_…" });
 *     await client.products.bulkUpsert([...]);
 *     const recs = await client.recommendations.get({ userId: "customer-42", topN: 6 });
 */
export class GraphRec {
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly maxBodyBytes: number;
  readonly maxBatchItems: number;
  readonly retryPolicy: RetryPolicy;

  private readonly apiKey?: string;
  private readonly accessToken?: string;
  private readonly email?: string;
  private readonly password?: string;
  private readonly platformToken?: string;
  private readonly defaultHeaders: Record<string, string>;
  private readonly fetchImpl: typeof fetch;
  private readonly useEnv: boolean;
  private session: PasswordSession | null = null;
  private loginInFlight: Promise<PasswordSession> | null = null;

  readonly tenants: Tenants;
  readonly auth: Auth;
  readonly apiKeys: ApiKeys;
  readonly subscription: Subscription;
  readonly usage: Usage;
  readonly products: Products;
  readonly events: Events;
  readonly datasets: Datasets;
  readonly modelVersions: ModelVersions;
  readonly trainingJobs: TrainingJobs;
  readonly deployment: Deployment;
  readonly metrics: Metrics;
  readonly recommendations: RecommendationsResource;
  readonly feedback: Feedback;
  readonly platform: Platform;

  constructor(options: GraphRecOptions = {}) {
    this.useEnv = options.useEnv ?? true;
    const env = (name: string) => (this.useEnv ? envVar(name) : undefined);
    this.baseUrl = (options.baseUrl ?? env(ENV_BASE_URL) ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.apiKey = options.apiKey ?? (options.accessToken || options.email || options.platformToken ? undefined : env(ENV_API_KEY));
    this.accessToken = options.accessToken ?? (this.apiKey || options.email || options.platformToken ? undefined : env(ENV_ACCESS_TOKEN));
    this.email = options.email;
    this.password = options.password;
    this.platformToken = options.platformToken;
    if ((this.email && !this.password) || (!this.email && this.password)) {
      throw new ConfigurationError("email and password must be given together");
    }
    const modes = [this.apiKey, this.accessToken, this.email].filter(Boolean).length;
    if (modes > 1) throw new ConfigurationError("Pass one of apiKey, accessToken, or email+password, not several");
    if (this.apiKey && !this.apiKey.startsWith(API_KEY_PREFIX)) {
      throw new ConfigurationError(`apiKey must start with ${API_KEY_PREFIX}`);
    }
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.maxBodyBytes = options.maxBodyBytes ?? DEFAULT_MAX_BODY_BYTES;
    this.maxBatchItems = options.maxBatchItems ?? DEFAULT_MAX_BATCH_ITEMS;
    this.retryPolicy = new RetryPolicy(options.retry);
    this.defaultHeaders = { ...(options.defaultHeaders ?? {}) };
    const fetchImpl = options.fetch ?? globalThis.fetch;
    if (typeof fetchImpl !== "function") throw new ConfigurationError("A global fetch is required (Node 18+), or pass options.fetch");
    this.fetchImpl = fetchImpl;

    this.tenants = new Tenants(this);
    this.auth = new Auth(this);
    this.apiKeys = new ApiKeys(this);
    this.subscription = new Subscription(this);
    this.usage = new Usage(this);
    this.products = new Products(this);
    this.events = new Events(this);
    this.datasets = new Datasets(this);
    this.modelVersions = new ModelVersions(this);
    this.trainingJobs = new TrainingJobs(this);
    this.deployment = new Deployment(this);
    this.metrics = new Metrics(this);
    this.recommendations = new RecommendationsResource(this);
    this.feedback = new Feedback(this);
    this.platform = new Platform(this);
  }

  /** A client for the same server with different credentials. */
  withCredentials(credentials: Pick<GraphRecOptions, "apiKey" | "accessToken" | "email" | "password" | "platformToken">): GraphRec {
    return new GraphRec({
      baseUrl: this.baseUrl,
      useEnv: false,
      timeoutMs: this.timeoutMs,
      maxBodyBytes: this.maxBodyBytes,
      maxBatchItems: this.maxBatchItems,
      retry: this.retryPolicy,
      defaultHeaders: this.defaultHeaders,
      fetch: this.fetchImpl,
      ...credentials,
    });
  }

  /** `GET /healthz`. */
  async health(): Promise<HealthStatus> {
    return this.request<HealthStatus>("health.check");
  }

  /** The scopes of the password session, once logged in (`null` for other credential kinds). */
  get sessionScopes(): string[] | null {
    return this.session?.token.scopes ?? null;
  }

  // ── transport ────────────────────────────────────────────────

  async request<T>(routeKey: string, options: RequestOptions = {}): Promise<T> {
    const r = route(routeKey);
    let reauthenticated = false;
    for (let attempt = 0; ; attempt += 1) {
      const authorization = await this.authorizationFor(r);
      const summary: RequestInfoSummary = { method: r.method, url: this.baseUrl + buildPath(r, options.params) };
      let response: Response;
      try {
        response = await this.send(r, options, authorization, summary);
      } catch (error) {
        const delay = this.retryPolicy.delayForTransport(error, r, attempt);
        if (delay === null) throw error;
        await sleep(delay);
        continue;
      }

      const text = await response.text();
      let body: unknown = null;
      if (text) {
        try {
          body = JSON.parse(text);
        } catch {
          body = text;
        }
      }
      if (response.ok) return this.validate<T>(response, body, summary);

      const error = errorFromResponse(response, body, summary);
      if (error instanceof TokenExpiredError && this.email && !reauthenticated) {
        // The server rejected the token before doing any work; log in once and resend.
        this.session = null;
        reauthenticated = true;
        continue;
      }
      const delay = this.retryPolicy.delayForStatus(error, r, attempt);
      if (delay === null) throw error;
      await sleep(delay);
    }
  }

  private async send(r: Route, options: RequestOptions, authorization: string | null, summary: RequestInfoSummary): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json", ...this.defaultHeaders, ...(options.headers ?? {}) };
    if (authorization) headers.Authorization = authorization;
    if (options.idempotencyKey) headers[HEADER_IDEMPOTENCY_KEY] = options.idempotencyKey;
    if (options.correlationId) headers[HEADER_CORRELATION_ID] = options.correlationId;
    headers["User-Agent"] = `graphrec-sdk-ts/${VERSION}`;

    let body: BodyInit | undefined;
    if (r.body === "json") {
      headers["Content-Type"] = "application/json";
      body = encodeJson(options.json ?? {});
    } else if (r.body === "multipart") {
      if (!options.multipart) throw new ConfigurationError(`${r.key} needs a multipart body`);
      body = options.multipart;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      return await this.fetchImpl(summary.url, { method: r.method, headers, body, signal: controller.signal });
    } catch (error) {
      if ((error as { name?: string })?.name === "AbortError") throw new APITimeoutError(undefined, { request: summary });
      throw new APIConnectionError(undefined, { request: summary, cause: error });
    } finally {
      clearTimeout(timer);
    }
  }

  private validate<T>(response: Response, body: unknown, summary: RequestInfoSummary): T {
    if (body === null || body === "") return {} as T;
    if (!isRecord(body) && !Array.isArray(body)) {
      throw new APIResponseValidationError("GraphRec returned a non-JSON success body", {
        status: response.status,
        body,
        request: summary,
        correlationId: response.headers.get(HEADER_CORRELATION_ID) ?? undefined,
      });
    }
    if (isRecord(body) && response.status === 200 && summary.url.endsWith("/v1/tenants") && summary.method === "POST") {
      return { ...body, replayed: true } as T;
    }
    if (isRecord(body) && response.status === 201 && summary.url.endsWith("/v1/tenants")) {
      return { ...body, replayed: false } as T;
    }
    return body as T;
  }

  // ── credentials ──────────────────────────────────────────────

  private async authorizationFor(r: Route): Promise<string | null> {
    if (r.auth === "none") return null;
    if (isPlatformRoute(r)) {
      const token = this.platformToken ?? this.accessToken;
      if (!token) throw new ConfigurationError("client.platform needs platformToken (the server's PLATFORM_ADMIN_TOKEN)");
      return `Bearer ${token}`;
    }
    if (r.auth === "bearer") {
      if (this.apiKey) throw new ConfigurationError(`${r.key} requires a user bearer token; API keys cannot call it`);
      return `Bearer ${await this.bearerToken(r.key)}`;
    }
    if (this.apiKey) return `ApiKey ${this.apiKey}`;
    if (this.accessToken || this.email) return `Bearer ${await this.bearerToken(r.key)}`;
    if (this.platformToken) throw new ConfigurationError(`${r.key} is a tenant route; the platform token only works for client.platform`);
    throw new ConfigurationError(`${r.key} requires credentials: pass apiKey, accessToken, or email+password`);
  }

  private async bearerToken(routeKey: string): Promise<string> {
    if (this.accessToken) return this.accessToken;
    if (!this.email || !this.password) throw new ConfigurationError(`${routeKey} requires a user bearer token`);
    const now = Date.now();
    if (this.session && this.session.expiresAt - TOKEN_EXPIRY_SKEW_SECONDS * 1000 > now) return this.session.token.access_token;
    if (!this.loginInFlight) {
      const email = this.email;
      const password = this.password;
      this.loginInFlight = this.auth
        .login({ email, password })
        .then((token) => {
          const session = { token, expiresAt: Date.now() + token.expires_in * 1000 };
          this.session = session;
          return session;
        })
        .finally(() => {
          this.loginInFlight = null;
        });
    }
    return (await this.loginInFlight).token.access_token;
  }
}
