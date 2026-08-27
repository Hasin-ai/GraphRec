import { resolveConfig } from './config.js';
import type { GraphRecOptions, ResolvedConfig } from './config.js';
import { Catalog } from './resources/catalog.js';
import { Events } from './resources/events.js';
import { Feedback } from './resources/feedback.js';
import { Recommendations } from './resources/recommendations.js';
import { Submissions } from './resources/submissions.js';
import { Transport } from './transport.js';

/**
 * The client. One object, four namespaces, two hosts you never choose between.
 *
 * Each namespace is constructed with the transport for the host that answers it,
 * so a data-plane call cannot be sent to the control host: there is no method
 * that would build that request. This is the whole reason the SDK is shaped as
 * namespaces rather than as a flat client with a `baseUrl` — see `config.ts` for
 * why that mistake is otherwise so quiet.
 *
 * ```ts
 * const gr = new GraphRec({
 *   apiKey: process.env.GRAPHREC_API_KEY!,
 *   tenantId: process.env.GRAPHREC_TENANT_ID!,
 *   domain: 'graphrec.example',
 * });
 *
 * const answer = await gr.recommendations.forCustomer({
 *   requestId: crypto.randomUUID(),
 *   customerId: 'customer-1',
 *   topN: 10,
 * });
 * ```
 */
export class GraphRec {
  /** Catalogue synchronisation. Control plane. Needs `catalog:write`. */
  readonly catalog: Catalog;
  /** Interaction events, one or many. Control plane. Needs `events:write`. */
  readonly events: Events;
  /** How a submission went. Control plane. Needs **`submissions:read`**. */
  readonly submissions: Submissions;
  /** The hot path. Data plane. Needs `recommendations:read`. */
  readonly recommendations: Recommendations;
  /** Impressions, clicks, conversions. Data plane. Needs `feedback:write`. */
  readonly feedback: Feedback;

  readonly #config: ResolvedConfig;

  constructor(options: GraphRecOptions) {
    const config = resolveConfig(options);
    this.#config = config;

    const control = new Transport(config.controlOrigin, config);
    const data = new Transport(config.dataOrigin, config);

    this.catalog = new Catalog(control);
    this.events = new Events(control);
    this.submissions = new Submissions(control);
    this.recommendations = new Recommendations(data);
    this.feedback = new Feedback(data);
  }

  /** The two origins this client will talk to. Useful in a startup log line. */
  get hosts(): { control: string; data: string } {
    return { control: this.#config.controlOrigin, data: this.#config.dataOrigin };
  }

  /**
   * The credential's public prefix, `gr_live_XXXX`.
   *
   * Safe to log, and worth logging: it is what a support conversation needs in
   * order to say *which* credential, and the console shows the same value in its
   * table. Everything after the separator is unreachable from here.
   */
  get credentialPrefix(): string {
    return this.#config.credential.prefix;
  }

  /**
   * Deliberately lossy, for the same reason `GeneratedSecret.__repr__` is.
   *
   * Without this, a structured logger, a crash reporter or a bare
   * `console.log(client)` walking own properties would print whatever the client
   * holds. It holds a `Credential`, whose secret is a `#private` field and so is
   * already invisible — this makes the intent explicit rather than incidental,
   * because the day someone adds a plain field is the day incidental stops
   * being enough.
   */
  toJSON(): Record<string, unknown> {
    return {
      control: this.#config.controlOrigin,
      data: this.#config.dataOrigin,
      credential: this.#config.credential.toString(),
    };
  }

  /**
   * The same summary as `inspect`, for the renderings that do not call it.
   *
   * A template literal, `String()` and most log formatters reach `toString`,
   * not the Node inspect hook, and the default gives `[object Object]` — safe,
   * but useless in the one line an operator has to work from. This says which
   * estate and which key without saying the key.
   */
  toString(): string {
    return `GraphRec(control=${this.#config.controlOrigin}, data=${this.#config.dataOrigin}, credential=${this.#config.credential.toString()})`;
  }

  [Symbol.for('nodejs.util.inspect.custom')](): string {
    return this.toString();
  }
}
