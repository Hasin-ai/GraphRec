import { Fragment, useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { SDK_REFERENCE as SDK } from "../../docs/sdkData";
import type { SdkMethod, SdkParam, SdkResource } from "../../docs/sdkTypes";
import { DocsCodeTabs } from "../../docs/DocsCodeTabs";
import { Icon } from "../../ui/icons";

// Everything on this page is generated from the SDK source by
// scripts/build_sdk_docs.py (signatures, docstrings, routes, errors, examples).

const C = SDK.constants;

const INSTALL = `# From a checkout of the GraphRec repository
pip install ./sdks/python

# Python ${SDK.requiresPython}; dependencies: ${SDK.dependencies.join(", ")}`;

const QUICKSTART = `import os
from graphrec_sdk import GraphRec, STOREFRONT_KEY_SCOPES

# 1. Storefront backend: an API key (events, recommendations, feedback)
client = GraphRec(base_url="https://graphrec.example.com", api_key="${C.API_KEY_PREFIX}...")
recs = client.storefront.recommendations.get(user_id="customer-42", top_n=8)
for item in recs.items:
    print(item.position, item.external_product_id)

# 2. Tenant administration: email + password (token renewed before expiry)
admin = GraphRec(email="admin@shop.example", password="...")
key = admin.tenant.api_keys.create(name="storefront", scopes=STOREFRONT_KEY_SCOPES)

# 3. Platform operations: the platform administrator token
ops = GraphRec(access_token=os.environ["PLATFORM_ADMIN_TOKEN"])
for tenant in ops.platform.tenants.list():
    print(tenant.slug, tenant.status)`;

const ASYNC = `import asyncio
from graphrec_sdk import AsyncGraphRec

async def main() -> None:
    async with AsyncGraphRec(api_key="${C.API_KEY_PREFIX}...") as client:
        recs = await client.storefront.recommendations.get(user_id="customer-42", top_n=5)
        print([item.external_product_id for item in recs.items])

asyncio.run(main())`;

const ERRORS = `from graphrec_sdk import GraphRec, NotFoundError, RateLimitError, APIStatusError

client = GraphRec()
try:
    product = client.tenant.catalog.get("SKU-404")
except NotFoundError:
    product = None
except RateLimitError as exc:        # retried automatically first; raised when retries run out
    print("slow down", exc)
except APIStatusError as exc:        # any other non-2xx response
    print(exc.status_code, exc)`;

const anchor = (s: string) => s.replace(/[^a-zA-Z0-9_-]/g, "-");

/** Render a docstring: paragraphs, indented code blocks and `inline code`. */
function DocText({ text }: { text: string }) {
  if (!text) return null;
  const blocks = text.split(/\n\s*\n/);
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        if (lines.every((l) => l.startsWith("    ") || !l.trim())) {
          return (
            <pre key={i} className="docs-signature-pre">
              <code>{lines.map((l) => l.slice(4)).join("\n")}</code>
            </pre>
          );
        }
        return <p key={i}>{inline(block.replace(/::$/, ":"))}</p>;
      })}
    </>
  );
}

function inline(text: string): ReactNode[] {
  return text.split(/(`[^`]+`)/g).map((part, i) =>
    part.startsWith("`") && part.endsWith("`") ? <code key={i}>{part.slice(1, -1)}</code> : <Fragment key={i}>{part}</Fragment>
  );
}

function ParamsTable({ params, withDescription }: { params: SdkParam[]; withDescription?: boolean }) {
  if (!params.length) return null;
  return (
    <div className="docs-table-wrapper">
      <table className="docs-table docs-param-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Required</th>
            <th>Default</th>
            {withDescription && <th>Description</th>}
          </tr>
        </thead>
        <tbody>
          {params.map((p) => (
            <tr key={p.name}>
              <td><code>{p.name}</code>{p.kind === "keyword" && <span className="badge badge-neutral" title="Keyword-only">kw</span>}</td>
              <td><code>{p.type || "Any"}</code></td>
              <td>
                {p.required ? <span className="badge badge-warning">Required</span> : <span className="badge badge-neutral">Optional</span>}
              </td>
              <td>{p.default !== null ? <code>{p.default}</code> : "—"}</td>
              {withDescription && <td>{p.description}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MethodCard({ method, highlighted }: { method: SdkMethod; highlighted: boolean }) {
  const id = anchor(method.call);
  return (
    <article id={id} className={`docs-endpoint-card ${highlighted ? "highlighted" : ""}`}>
      <header className="docs-endpoint-header">
        <div className="docs-endpoint-title-row">
          <code className="docs-method-title">.{method.name}()</code>
          {method.routes.map((r) => (
            <span key={r.key} className="docs-endpoint-badges">
              <span className={`docs-method-badge method-${r.method.toLowerCase()}`}>{r.method}</span>
              <code className="docs-endpoint-path">{r.path}</code>
              {r.scopes.map((s) => (
                <span key={s} className="docs-scope-badge" title="Required scope">{s}</span>
              ))}
              {r.auth === "none" && <span className="docs-auth-badge auth-public">Public</span>}
              {r.auth === "bearer" && <span className="docs-auth-badge auth-bearer">User token</span>}
            </span>
          ))}
        </div>
        <pre className="docs-signature-pre">
          <code>{method.signature}</code>
        </pre>
      </header>
      <div className="docs-endpoint-body">
        <div className="docs-sub-section">
          {method.doc ? (
            <DocText text={method.doc} />
          ) : method.routes.length ? (
            <p>
              Calls <code>{method.routes.map((r) => `${r.method} ${r.path}`).join(", ")}</code>.
            </p>
          ) : null}
        </div>
        <div className="docs-sub-section">
          <h4>Arguments</h4>
          {method.params.length ? <ParamsTable params={method.params} /> : <p>None.</p>}
        </div>
        {method.returns && (
          <div className="docs-sub-section">
            <h4>Returns</h4>
            <p><code>{method.returns}</code></p>
          </div>
        )}
        {method.routes.length > 0 && method.routes.every((r) => r.idempotent) && (
          <p className="docs-endpoint-summary">
            Idempotent: the SDK also retries this call after timeouts and dropped connections.
          </p>
        )}
      </div>
    </article>
  );
}

function matches(m: SdkMethod, q: string) {
  if (!q) return true;
  const hay = `${m.call} ${m.signature} ${m.doc} ${m.routes.map((r) => r.path + " " + r.scopes.join(" ")).join(" ")}`.toLowerCase();
  return q.split(/\s+/).every((t) => hay.includes(t));
}

function ResourceSection({ res, q, hash }: { res: SdkResource; q: string; hash: string }) {
  const methods = res.methods.filter((m) => matches(m, q));
  if (q && !methods.length) return null;
  return (
    <div className="docs-sdk-resource">
      <h3 id={res.id}>
        <code>{res.path}</code>
      </h3>
      <p className="docs-endpoint-summary">
        <code>{res.className}</code>
        {res.asyncClass && (
          <>
            {" "}· async: <code>{res.asyncClass}</code>
          </>
        )}{" "}
        · {res.methods.length} method{res.methods.length === 1 ? "" : "s"}
      </p>
      {res.doc && <DocText text={res.doc} />}
      {res.ctor && (
        <pre className="docs-signature-pre">
          <code>{res.ctor}</code>
        </pre>
      )}
      <div className="docs-sdk-methods-list">
        {methods.map((m) => (
          <MethodCard key={m.call} method={m} highlighted={hash === `#${anchor(m.call)}`} />
        ))}
      </div>
    </div>
  );
}

export function DocsSdkPage() {
  const { hash } = useLocation();
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();

  const hits = useMemo(() => {
    const all = [
      ...SDK.clientMethods,
      ...SDK.namespaces.flatMap((n) => n.resources.flatMap((r) => r.methods)),
      ...SDK.helpers.flatMap((h) => h.methods),
    ];
    return q ? all.filter((m) => matches(m, q)).length : all.length;
  }, [q]);

  const clientResource: SdkResource = {
    id: "client-methods",
    path: "client",
    title: "client",
    className: "GraphRec",
    asyncClass: "AsyncGraphRec",
    doc: "Service checks and credential helpers on the client itself.",
    methods: SDK.clientMethods,
  };

  return (
    <div className="docs-page">
      <header className="docs-page-header">
        <div className="docs-breadcrumbs">
          <Link to="/docs">Docs</Link>
          <span className="separator">/</span>
          <span>Python SDK Reference</span>
        </div>
        <h1>Python SDK Reference</h1>
        <p className="lead">
          <code>{SDK.package}</code> {SDK.version} — synchronous and asynchronous clients for every GraphRec API: {SDK.stats.methods}{" "}
          methods covering all {SDK.stats.routes} routes, typed models, automatic retries, idempotency keys, bulk chunking and
          e-commerce helpers.
        </p>
        <div className="docs-callout docs-callout-info">
          <div className="docs-callout-title">Generated from the SDK source</div>
          <p>
            Signatures, docstrings, routes, scopes, errors and examples on this page are extracted from{" "}
            <code>sdks/python/src/graphrec_sdk</code> by <code>scripts/build_sdk_docs.py</code>, so they match the code you install.
          </p>
        </div>
      </header>

      <section className="docs-section">
        <h2 id="installation">Installation</h2>
        <p>
          The SDK lives in the GraphRec repository under <code>sdks/python</code>. It needs Python {SDK.requiresPython} and depends
          only on {SDK.dependencies.map((d, i) => (
            <Fragment key={d}>{i > 0 && " and "}<code>{d}</code></Fragment>
          ))}
          .
        </p>
        <DocsCodeTabs title="Terminal" curl={INSTALL} />
      </section>

      <section className="docs-section">
        <h2 id="quickstart">Quickstart</h2>
        <p>
          One client class, three kinds of credential. Resources are grouped by who calls them: <code>client.storefront</code>,{" "}
          <code>client.tenant</code> and <code>client.platform</code>.
        </p>
        <DocsCodeTabs title="Three ways to authenticate" python={QUICKSTART} />
      </section>

      <section className="docs-section">
        <h2 id="configuration">Client configuration</h2>
        <p>
          <code>GraphRec(...)</code> and <code>AsyncGraphRec(...)</code> take the same keyword-only arguments:
        </p>
        <ParamsTable params={SDK.clientParams} withDescription />
        <h3 id="environment">Environment variables</h3>
        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr><th>Variable</th><th>Used for</th></tr>
            </thead>
            <tbody>
              <tr><td><code>{C.ENV_BASE_URL}</code></td><td><code>base_url</code> (default <code>{C.DEFAULT_BASE_URL}</code>)</td></tr>
              <tr><td><code>{C.ENV_API_KEY}</code></td><td><code>api_key</code></td></tr>
              <tr><td><code>{C.ENV_ACCESS_TOKEN}</code></td><td><code>access_token</code> (used when no API key is set)</td></tr>
            </tbody>
          </table>
        </div>
        <h3 id="behaviour">Built-in behaviour</h3>
        <ul>
          <li>
            <strong>Retries.</strong> Up to <code>{C.DEFAULT_MAX_RETRIES}</code> retries with exponential backoff. Rate limits (429),
            declared-retryable 503s and failures before the request is sent are retried on every route. Ambiguous failures (read
            timeouts, dropped connections, 502/504) are retried only on idempotent routes. A server <code>Retry-After</code> of up to{" "}
            {C.MAX_RETRY_AFTER_SECONDS} s is honoured.
          </li>
          <li>
            <strong>Idempotency.</strong> Events and feedback carry an <code>event_id</code> (generated when you omit it; use{" "}
            <code>deterministic_id()</code> for replay-safe ids), and bulk upserts send an <code>{C.HEADER_IDEMPOTENCY_KEY}</code>, so a
            retried request is not applied twice.
          </li>
          <li>
            <strong>Bulk chunking.</strong> Bulk helpers split payloads to stay under {Number(C.DEFAULT_MAX_BODY_BYTES) / 1024} KiB and{" "}
            {C.DEFAULT_MAX_BATCH_ITEMS} items per request.
          </li>
          <li>
            <strong>Sessions.</strong> With <code>email</code>/<code>password</code> the SDK logs in lazily and renews the access token{" "}
            {C.TOKEN_EXPIRY_SKEW_SECONDS} s before it expires.
          </li>
          <li>
            <strong>Tracing.</strong> Every error carries the server's <code>{C.HEADER_CORRELATION_ID}</code> for support requests.
          </li>
        </ul>
        <h3 id="async">Async client</h3>
        <p>
          <code>AsyncGraphRec</code> exposes the same namespaces and methods; await each call and use <code>async with</code> to close
          the connection pool.
        </p>
        <DocsCodeTabs title="AsyncGraphRec" python={ASYNC} />
      </section>

      <section className="docs-section">
        <h2 id="reference">API reference</h2>
        <div className="docs-grid-3">
          {SDK.namespaces.map((ns) => (
            <div key={ns.name} className="docs-card">
              <h4>
                <a href={`#${ns.name}`}><code>{ns.path}</code></a>
              </h4>
              <p>{ns.doc}</p>
              <ul>
                {ns.resources.map((r) => (
                  <li key={r.id}>
                    <a href={`#${r.id}`}><code>{r.title}</code></a> ({r.methods.length})
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="docs-ref-search-box" style={{ margin: "1.5rem 0" }}>
          <Icon name="search" size={14} />
          <input
            type="search"
            placeholder="Filter methods by name, path, scope or text…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Filter SDK methods"
          />
          <span className="badge badge-neutral" aria-live="polite">{hits} methods</span>
        </div>
        <ResourceSection res={clientResource} q={q} hash={hash} />
      </section>

      {SDK.namespaces.map((ns) => (
        <section key={ns.name} className="docs-section">
          <h2 id={ns.name}>
            <code>{ns.path}</code>
          </h2>
          <p>{ns.doc}</p>
          {ns.resources.map((r) => (
            <ResourceSection key={r.id} res={r} q={q} hash={hash} />
          ))}
        </section>
      ))}

      <section className="docs-section">
        <h2 id="ecommerce">E-commerce helpers</h2>
        <p>
          <code>graphrec_sdk.ecommerce</code> wraps the raw resources for common shop integrations. Each helper has an{" "}
          <code>Async…</code> variant for <code>AsyncGraphRec</code>.
        </p>
        {SDK.helpers.map((h) => (
          <ResourceSection key={h.id} res={h} q={q} hash={hash} />
        ))}
      </section>

      <section className="docs-section">
        <h2 id="errors">Errors</h2>
        <p>
          Every exception derives from <code>GraphRecError</code>. HTTP failures raise an <code>APIStatusError</code> subclass chosen by
          the server's error <code>code</code>, falling back to the HTTP status.
        </p>
        <DocsCodeTabs title="Handling errors" python={ERRORS} />
        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead>
              <tr><th>Exception</th><th>Parent</th><th>HTTP status</th><th>Error codes</th><th>Meaning</th></tr>
            </thead>
            <tbody>
              {SDK.errors.map((e) => (
                <tr key={e.name} id={`error-${e.name}`}>
                  <td><code>{e.name}</code></td>
                  <td><code>{e.base}</code></td>
                  <td>{e.statuses.length ? e.statuses.join(", ") : "—"}</td>
                  <td>{e.codes.length ? e.codes.map((c) => <code key={c} style={{ marginRight: 4 }}>{c}</code>) : "—"}</td>
                  <td>{inline(e.doc)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="docs-section">
        <h2 id="types">Enums and scopes</h2>
        <h3 id="enums">Enums</h3>
        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead><tr><th>Enum</th><th>Values</th></tr></thead>
            <tbody>
              {SDK.enums.map((e) => (
                <tr key={e.name}>
                  <td><code>{e.name}</code></td>
                  <td>{e.values.map((v) => <code key={v} style={{ marginRight: 4 }}>{v}</code>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 id="scopes">Scope bundles</h3>
        <p>Pass these to <code>client.tenant.api_keys.create(scopes=…)</code> instead of listing scopes by hand.</p>
        <div className="docs-table-wrapper">
          <table className="docs-table">
            <thead><tr><th>Constant</th><th>Scopes</th></tr></thead>
            <tbody>
              {Object.entries(SDK.scopeSets).map(([name, val]) =>
                Array.isArray(val) ? (
                  <tr key={name}>
                    <td><code>{name}</code></td>
                    <td>{val.map((s) => <code key={s} style={{ marginRight: 4 }}>{s}</code>)}</td>
                  </tr>
                ) : (
                  Object.entries(val).map(([role, list]) => (
                    <tr key={`${name}-${role}`}>
                      <td><code>{name}["{role}"]</code></td>
                      <td>{list.map((s) => <code key={s} style={{ marginRight: 4 }}>{s}</code>)}</td>
                    </tr>
                  ))
                )
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="docs-section">
        <h2 id="examples">Runnable examples</h2>
        <p>
          Complete scripts from <code>sdks/python/examples</code>. Point them at your stack with <code>{C.ENV_BASE_URL}</code> and the
          credential variables above.
        </p>
        {SDK.examples.map((ex) => (
          <details key={ex.file} className="docs-card" style={{ marginBottom: "1rem" }}>
            <summary>
              <strong>{ex.title}</strong> <code>{ex.file}</code>
            </summary>
            <DocsCodeTabs title={ex.file.split("/").pop()} python={ex.code} />
          </details>
        ))}
      </section>
    </div>
  );
}
