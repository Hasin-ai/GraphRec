/**
 * Contract tests: the SDK route table, wire types and request bodies against the
 * FastAPI source and the Python SDK.
 *
 * The backend is read as text (no Python runtime needed). The tests run when the
 * SDK lives inside the GraphRec repository (`sdks/typescript`) and are skipped
 * otherwise.
 */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { API_KEY_SCOPES, DELEGATABLE_SCOPES, ROLE_SCOPES, ROUTES, requiredScopes, type Route } from "../src/index.js";
import { client, mockFetch } from "./helpers.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..");
const ROUTES_DIR = join(REPO_ROOT, "apps", "api", "routes");
const SCHEMAS_DIR = join(REPO_ROOT, "graphrec_core", "schemas");
const PYTHON_ROUTES = join(REPO_ROOT, "sdks", "python", "src", "graphrec_sdk", "_routes.py");
const TYPES_TS = resolve(HERE, "..", "src", "types.ts");

const available = existsSync(ROUTES_DIR) && existsSync(SCHEMAS_DIR);
const suite = available ? describe : describe.skip;

const read = (path: string) => readFileSync(path, "utf8").replace(/\r\n/g, "\n");

/** Index just past the parenthesis that closes the one at `open`. */
function closingParen(text: string, open: number): number {
  let depth = 0;
  let quote: string | null = null;
  for (let i = open; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (ch === "\\") i += 1;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "(" || ch === "[" || ch === "{") depth += 1;
    else if (ch === ")" || ch === "]" || ch === "}") {
      depth -= 1;
      if (depth === 0) return i + 1;
    }
  }
  throw new Error("Unbalanced parentheses");
}

/** Split on commas at nesting depth 0. */
function splitTopLevel(text: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let start = 0;
  let quote: string | null = null;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (ch === "\\") i += 1;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if ("([{".includes(ch)) depth += 1;
    else if (")]}".includes(ch)) depth -= 1;
    else if (ch === "," && depth === 0) {
      parts.push(text.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(text.slice(start));
  return parts.map((p) => p.trim()).filter(Boolean);
}

const stringLiterals = (text: string): string[] => Array.from(text.matchAll(/"([^"]*)"/g), (m) => m[1]);

// ── server routes ───────────────────────────────────────────────

interface ServerRoute {
  method: string;
  path: string;
  body: "none" | "json" | "multipart";
  authenticated: boolean;
  bearerOnly: boolean;
  scopes: Set<string>;
}

/** Router/endpoint dependencies that authenticate with an `Authorization: Bearer` secret. */
const BEARER_DEPENDENCIES = new Set(["platform_administrator"]);
const NON_BODY_ANNOTATIONS = new Set(["Request", "Response", "Session", "UUID", "str", "int", "AuthenticatedPrincipal", "Settings"]);

function parseRouterFile(source: string, decoratorTarget: "router" | "app"): ServerRoute[] {
  let prefix = "";
  const routerDependencies = new Set<string>();
  const routerDecl = source.match(/^router\s*=\s*APIRouter\(/m);
  if (routerDecl) {
    const open = routerDecl.index! + routerDecl[0].length - 1;
    const args = source.slice(open + 1, closingParen(source, open) - 1);
    for (const arg of splitTopLevel(args)) {
      const [name, value] = arg.split(/=(.*)/s).map((s) => s.trim());
      if (name === "prefix") prefix = stringLiterals(value)[0] ?? "";
      if (name === "dependencies") for (const m of value.matchAll(/Depends\((\w+)\)/g)) routerDependencies.add(m[1]);
    }
  }

  // Module-level helper functions (e.g. `_authorize`) may carry scope checks for an endpoint.
  const helpers = new Map<string, string>();
  for (const m of source.matchAll(/^def (\w+)\(/gm)) {
    const sigEnd = closingParen(source, m.index! + m[0].length - 1);
    const bodyEnd = source.slice(sigEnd).search(/\n\S/);
    helpers.set(m[1], source.slice(sigEnd, bodyEnd === -1 ? undefined : sigEnd + bodyEnd));
  }

  const routes: ServerRoute[] = [];
  const decorator = new RegExp(`^@${decoratorTarget}\\.(get|post|put|patch|delete)\\(\\s*"([^"]*)"`, "gm");
  for (const m of source.matchAll(decorator)) {
    const route: ServerRoute = {
      method: m[1].toUpperCase(),
      path: prefix + m[2],
      body: "none",
      authenticated: routerDependencies.size > 0,
      bearerOnly: [...routerDependencies].some((d) => BEARER_DEPENDENCIES.has(d)),
      scopes: new Set(),
    };
    const def = source.slice(m.index!).match(/\n(?:async )?def \w+\(/);
    const sigOpen = m.index! + def!.index! + def![0].length - 1;
    const sigEnd = closingParen(source, sigOpen);
    const signature = source.slice(sigOpen + 1, sigEnd - 1);
    for (const param of splitTopLevel(signature)) {
      const [left, defaultValue = ""] = param.split(/=(.*)/s).map((s) => s.trim());
      const [, annotation = ""] = left.split(/:(.*)/s).map((s) => s.trim());
      const defaultCall = defaultValue.match(/^(\w+)\(/)?.[1] ?? "";
      if (annotation === "AuthenticatedPrincipal") route.authenticated = true;
      else if (defaultCall === "File") route.body = "multipart";
      else if (defaultCall === "Depends" || defaultCall === "Header") continue;
      else if (annotation && !NON_BODY_ANNOTATIONS.has(annotation.split("[")[0])) route.body = "json";
    }
    const bodyEnd = source.slice(sigEnd).search(/\n\S/);
    let body = source.slice(sigEnd, bodyEnd === -1 ? undefined : sigEnd + bodyEnd);
    for (const call of body.matchAll(/\b(\w+)\(/g)) if (helpers.has(call[1])) body += helpers.get(call[1]);
    if (/require_bearer\(/.test(body)) route.bearerOnly = true;
    for (const scope of body.matchAll(/require_scope\(\s*"([^"]+)"/g)) route.scopes.add(scope[1]);
    routes.push(route);
  }
  return routes;
}

function serverRoutes(): Map<string, ServerRoute> {
  const found = new Map<string, ServerRoute>();
  for (const file of readdirSync(ROUTES_DIR).filter((f) => f.endsWith(".py")).sort()) {
    for (const r of parseRouterFile(read(join(ROUTES_DIR, file)), "router")) found.set(`${r.method} ${r.path}`, r);
  }
  for (const r of parseRouterFile(read(join(REPO_ROOT, "apps", "api", "main.py")), "app")) found.set(`${r.method} ${r.path}`, r);
  return found;
}

// ── server schemas ──────────────────────────────────────────────

interface SchemaField {
  name: string;
  required: boolean;
}

function schemaClasses(): Map<string, { bases: string[]; fields: SchemaField[] }> {
  const classes = new Map<string, { bases: string[]; fields: SchemaField[] }>();
  const files = [
    ...readdirSync(SCHEMAS_DIR).filter((f) => f.endsWith(".py")).map((f) => join(SCHEMAS_DIR, f)),
    ...readdirSync(ROUTES_DIR).filter((f) => f.endsWith(".py")).map((f) => join(ROUTES_DIR, f)),
  ];
  for (const file of files) {
    const source = read(file);
    for (const m of source.matchAll(/^class (\w+)\(([^)]*)\):\n/gm)) {
      const start = m.index! + m[0].length;
      const end = source.slice(start).search(/\n\S/);
      const block = source.slice(start, end === -1 ? undefined : start + end);
      const fields: SchemaField[] = [];
      const statement = /^ {4}(\w+):[^\n=]*(=)?/gm;
      for (const s of block.matchAll(statement)) {
        const name = s[1];
        if (name === "model_config") continue;
        let required = s[2] === undefined;
        if (!required) {
          const eq = block.indexOf("=", s.index!);
          let value = block.slice(eq + 1).trimStart();
          if (value.startsWith("Field(")) {
            value = value.slice(0, closingParen(value, 5));
            const args = splitTopLevel(value.slice(6, -1));
            const first = args[0];
            const hasDefault = args.some((a) => /^(default|default_factory)\s*=/.test(a));
            required = first === "..." || (!!first && first.includes("=") && !hasDefault) || (!first && !hasDefault);
          }
        }
        fields.push({ name, required });
      }
      classes.set(m[1], { bases: m[2].split(",").map((b) => b.trim()), fields });
    }
  }
  return classes;
}

function schemaFields(name: string, classes = schemaClasses()): Map<string, SchemaField> {
  const entry = classes.get(name);
  if (!entry) throw new Error(`Server schema ${name} not found`);
  const merged = new Map<string, SchemaField>();
  for (const base of entry.bases) if (classes.has(base)) for (const [k, v] of schemaFields(base, classes)) merged.set(k, v);
  for (const f of entry.fields) merged.set(f.name, f);
  return merged;
}

// ── SDK wire types (src/types.ts) ───────────────────────────────

interface TsField {
  name: string;
  optional: boolean;
}

function tsInterfaces(): Map<string, { base?: string; fields: TsField[] }> {
  const source = read(TYPES_TS);
  const found = new Map<string, { base?: string; fields: TsField[] }>();
  for (const m of source.matchAll(/^export interface (\w+)(?: extends (\w+))? \{\n([\s\S]*?)\n\}/gm)) {
    const fields = Array.from(m[3].matchAll(/^\s+(\w+)(\?)?:/gm), (f) => ({ name: f[1], optional: f[2] === "?" }));
    found.set(m[1], { base: m[2], fields });
  }
  return found;
}

function tsFields(name: string, interfaces = tsInterfaces()): Map<string, TsField> {
  const entry = interfaces.get(name);
  if (!entry) throw new Error(`SDK type ${name} not found in types.ts`);
  const merged = entry.base ? tsFields(entry.base, interfaces) : new Map<string, TsField>();
  for (const f of entry.fields) merged.set(f.name, f);
  return merged;
}

// ── Python SDK route table ──────────────────────────────────────

interface PyRoute {
  key: string;
  method: string;
  path: string;
  auth: string;
  scope?: string;
  extraScopes: string[];
  idempotent: boolean;
  body: string;
}

function pythonRoutes(): Map<string, PyRoute> {
  const source = read(PYTHON_ROUTES);
  const found = new Map<string, PyRoute>();
  for (const m of source.matchAll(/Route\(/g)) {
    const open = m.index! + m[0].length - 1;
    const args = splitTopLevel(source.slice(open + 1, closingParen(source, open) - 1));
    const [key, method, path] = args.slice(0, 3).map((a) => stringLiterals(a)[0]);
    if (!key || !method || !path || key === "key") continue; // skip the dataclass definition itself
    const kw: Record<string, string> = {};
    for (const arg of args.slice(3)) {
      const [name, value] = arg.split(/=(.*)/s).map((s) => s.trim());
      kw[name] = value;
    }
    found.set(key, {
      key,
      method,
      path,
      auth: kw.auth ? stringLiterals(kw.auth)[0] : "any",
      scope: kw.scope ? stringLiterals(kw.scope)[0] : undefined,
      extraScopes: kw.extra_scopes ? stringLiterals(kw.extra_scopes) : [],
      idempotent: kw.idempotent === "True",
      body: kw.body ? stringLiterals(kw.body)[0] : "none",
    });
  }
  return found;
}

// ── tests ───────────────────────────────────────────────────────

suite("routes", () => {
  const server = serverRoutes();
  const sdk = [...ROUTES.values()];

  it("finds the server's routes", () => {
    expect(server.size).toBeGreaterThanOrEqual(50);
  });

  it("covers exactly the server routes", () => {
    const serverKeys = new Set(server.keys());
    const sdkKeys = new Set(sdk.map((r) => `${r.method} ${r.path}`));
    expect([...sdkKeys].filter((k) => !serverKeys.has(k)), "SDK calls routes the server does not define").toEqual([]);
    expect([...serverKeys].filter((k) => !sdkKeys.has(k)), "Server routes missing from the SDK").toEqual([]);
  });

  for (const r of sdk) {
    it(`${r.key} matches the server`, () => {
      const s = server.get(`${r.method} ${r.path}`)!;
      expect(s, `server route for ${r.key}`).toBeDefined();
      expect(r.body, `body kind for ${r.key}`).toBe(s.body);
      if (s.authenticated) expect(["any", "bearer"], `${r.key} requires credentials on the server`).toContain(r.auth);
      else expect(r.auth, `${r.key} is public on the server`).toBe("none");
      expect(r.auth === "bearer", `bearer-only mismatch for ${r.key}`).toBe(s.bearerOnly);
      if (s.scopes.size) expect(new Set(requiredScopes(r)), `scopes for ${r.key}`).toEqual(s.scopes);
      else expect(requiredScopes(r).filter((scope) => scope !== "platform:admin"), `${r.key} has no scope check on the server`).toEqual([]);
    });
  }
});

suite("python sdk parity", () => {
  const python = pythonRoutes();

  it("has the same route keys as the Python SDK", () => {
    expect([...ROUTES.keys()].sort()).toEqual([...python.keys()].sort());
  });

  for (const r of ROUTES.values()) {
    it(`${r.key} matches the Python route`, () => {
      const p = python.get(r.key)!;
      const tsView: PyRoute = { key: r.key, method: r.method, path: r.path, auth: r.auth, scope: r.scope, extraScopes: [...r.extraScopes], idempotent: r.idempotent, body: r.body };
      expect(tsView).toEqual(p);
    });
  }
});

/** Server response schema -> SDK interface. */
const RESPONSE_TYPES: [string, string][] = [
  ["TenantRegistrationResponse", "TenantRegistration"],
  ["AuthTokenPair", "TokenPair"],
  ["ApiKeyResponse", "ApiKey"],
  ["ApiKeySecretResponse", "ApiKeyWithSecret"],
  ["ApiKeyListResponse", "ApiKeyList"],
  ["SubscriptionResponse", "Subscription"],
  ["UsageDimension", "UsageDimension"],
  ["UsageSummaryResponse", "UsageSummary"],
  ["ProductResource", "Product"],
  ["ProductListResponse", "ProductList"],
  ["ProductBulkFailure", "BulkUpsertFailure"],
  ["ProductBulkUpsertResponse", "ProductBulkUpsertResult"],
  ["EventBatchResponse", "EventBatch"],
  ["DatasetSnapshotResource", "DatasetSnapshot"],
  ["DatasetSnapshotListResponse", "DatasetSnapshotList"],
  ["DatasetUploadResponse", "DatasetUploadResult"],
  ["ModelVersionResource", "ModelVersion"],
  ["ModelVersionListResponse", "ModelVersionList"],
  ["TrainingJobResource", "TrainingJob"],
  ["TrainingJobListResponse", "TrainingJobList"],
  ["DeploymentStatus", "DeploymentStatus"],
  ["ReplicaItem", "Replica"],
  ["ReplicaStatusResponse", "ReplicaStatus"],
  ["AutoscalingStatus", "AutoscalingStatus"],
  ["QualitySummary", "QualitySummary"],
  ["MetricsSummary", "MetricsSummary"],
  ["RecommendationItem", "RecommendationItem"],
  ["RecommendationResponse", "Recommendations"],
  ["FeedbackResponse", "FeedbackReceipt"],
  ["PlatformTenantResource", "PlatformTenant"],
  ["PlatformTenantListResponse", "PlatformTenantList"],
  ["PlatformPlanResource", "PricingPlan"],
  ["PlatformQuotaOverride", "QuotaOverride"],
  ["PlatformFailureItem", "PlatformFailure"],
  ["PlatformFailureListResponse", "PlatformFailureList"],
  ["PlatformAuditItem", "AuditRecord"],
  ["PlatformAuditListResponse", "AuditRecordList"],
];

/** Fields the SDK computes itself and never expects from the server. */
const SDK_ONLY_FIELDS = new Set(["request_count", "replayed"]);

suite("response types", () => {
  const classes = schemaClasses();
  const interfaces = tsInterfaces();
  for (const [schema, type] of RESPONSE_TYPES) {
    it(`${type} matches ${schema}`, () => {
      const server = schemaFields(schema, classes);
      const sdk = tsFields(type, interfaces);
      expect([...server.keys()].filter((f) => !sdk.has(f)), `${type} lacks server fields`).toEqual([]);
      expect([...sdk.keys()].filter((f) => !server.has(f) && !SDK_ONLY_FIELDS.has(f)), `${type} declares fields the server never sends`).toEqual([]);
    });
  }
});

suite("request bodies", () => {
  const classes = schemaClasses();
  const recs = { request_id: "rec-1", items: [{ external_product_id: "a", position: 1 }], model_version_id: null, strategy: "personalized", fallback_used: false, fallback_tier: "none" };
  const ok = { body: {} };

  /** Send one SDK call against a recording fetch and return the JSON body it produced. */
  async function bodyOf(schema: string, call: (c: ReturnType<typeof client>) => Promise<unknown>, credentials: Record<string, string> = { apiKey: "gr_live_x" }): Promise<Record<string, unknown>> {
    const mock = mockFetch(ok);
    await call(client(mock, credentials));
    const last = mock.calls[mock.calls.length - 1];
    expect(last.body, `${schema}: request body`).toBeTypeOf("object");
    return last.body as Record<string, unknown>;
  }

  const bearer = { accessToken: "tok" };
  const platform = { platformToken: "secret-secret-secret-secret-secret" };
  const CASES: [string, () => Promise<Record<string, unknown>>][] = [
    ["ProductUpsert", () => bodyOf("ProductUpsert", (c) => c.products.upsert({ external_id: "a", title: "b", description: "d", price: "1.00", category: "c", is_active: true, availability_status: "available", metadata: { k: 1 } }))],
    ["EventSubmit", () => bodyOf("EventSubmit", (c) => c.events.create({ event_type: "view", user_id: "u", external_product_id: "p", context: {}, occurred_at: new Date() }))],
    ["ModelVersionCreate", () => bodyOf("ModelVersionCreate", (c) => c.modelVersions.create({ version_tag: "v1", model_type: "simplified_dgsr", metrics: { a: 1 }, artifact_uri: "uri" }))],
    ["TrainingJobCreate", () => bodyOf("TrainingJobCreate", (c) => c.trainingJobs.create({ model_type: "simplified_dgsr", dataset_snapshot_id: "3f0e2b8e-9c1d-4c1e-8e2a-000000000001", configuration: { a: 1 } }))],
    ["DatasetSnapshotCreate", () => bodyOf("DatasetSnapshotCreate", (c) => c.datasets.createSnapshot({ cutoffAt: new Date(), description: "weekly" }))],
    ["ApiKeyCreateRequest", () => bodyOf("ApiKeyCreateRequest", (c) => c.apiKeys.create({ name: "k", scopes: ["catalog:read"] }), bearer)],
    ["ApiKeyRotateRequest", () => bodyOf("ApiKeyRotateRequest", (c) => c.apiKeys.rotate("id", { reason: "reason", gracePeriodSeconds: 0 }), bearer)],
    ["RecommendationRequest", () => bodyOf("RecommendationRequest", (c) => c.recommendations.get({ userId: "u", topN: 5, context: {}, excludeProductIds: ["x"] }))],
    ["RecommendationRequest (session)", () => bodyOf("RecommendationRequest", (c) => c.recommendations.forSession({ sessionId: "s", recentProductIds: ["a"], topN: 5 }))],
    ["ImpressionFeedback", () => bodyOf("ImpressionFeedback", (c) => c.feedback.impression(recs))],
    ["ClickFeedback", () => bodyOf("ClickFeedback", (c) => c.feedback.click(recs, "a", { impressionEventId: "i" }))],
    ["ConversionFeedback", () => bodyOf("ConversionFeedback", (c) => c.feedback.conversion(recs, "a", { value: 1 }))],
    ["TenantStatusUpdate", () => bodyOf("TenantStatusUpdate", (c) => c.platform.setTenantStatus("t", "suspended"), platform)],
    ["QuotaOverrideUpdate", () => bodyOf("QuotaOverrideUpdate", (c) => c.platform.setQuotaOverride("t", { accepted_events: 1 }), platform)],
    ["LoginRequest", () => bodyOf("LoginRequest", (c) => c.auth.login({ email: "a@b.test", password: "x" }), {})],
    ["SetupPasswordRequest", () => bodyOf("SetupPasswordRequest", (c) => c.auth.setupPassword({ setupToken: "t".repeat(43), password: "x".repeat(8), email: "a@b.test" }), {})],
    ["TenantRegistrationRequest", () => bodyOf("TenantRegistrationRequest", (c) => c.tenants.register({ name: "n", admin_email: "a@b.test" }), {})],
  ];

  for (const [label, build] of CASES) {
    it(`${label} fits the server schema`, async () => {
      const schema = label.split(" ")[0];
      const server = schemaFields(schema, classes);
      const body = await build();
      expect(Object.keys(body).filter((f) => !server.has(f)), `SDK sends fields ${schema} does not declare`).toEqual([]);
      const required = [...server.values()].filter((f) => f.required).map((f) => f.name);
      expect(required.filter((f) => !(f in body)), `SDK omits required ${schema} fields`).toEqual([]);
    });
  }
});

suite("scopes", () => {
  function pyStringSet(source: string, name: string): Set<string> {
    const decl = source.match(new RegExp(`^${name}(?::[^=\\n]*)?\\s*=\\s*`, "m"));
    if (!decl) throw new Error(`${name} not found`);
    let rest = source.slice(decl.index! + decl[0].length);
    const alias = rest.match(/^(\w+)\s*$/m);
    if (alias && rest.indexOf(alias[1]) === 0) return pyStringSet(source, alias[1]); // `X = Y`
    const open = rest.search(/[([{]/);
    rest = rest.slice(open, closingParen(rest, open));
    return new Set(stringLiterals(rest));
  }

  it("role scopes match graphrec_core/auth/service.py", () => {
    const source = read(join(REPO_ROOT, "graphrec_core", "auth", "service.py"));
    const block = source.slice(source.indexOf("ROLE_SCOPES"));
    const open = block.indexOf("{");
    const dict = block.slice(open, closingParen(block, open));
    const roles: Record<string, Set<string>> = {};
    for (const m of dict.matchAll(/"(tenant_\w+)":\s*\[/g)) {
      const open = m.index! + m[0].length - 1;
      roles[m[1]] = new Set(stringLiterals(dict.slice(open, closingParen(dict, open))));
    }
    expect(Object.keys(roles).sort()).toEqual(Object.keys(ROLE_SCOPES).sort());
    for (const [role, scopes] of Object.entries(ROLE_SCOPES)) expect(new Set(scopes), role).toEqual(roles[role]);
  });

  it("API-key and delegation scopes match graphrec_core/api_keys/scopes.py", () => {
    const source = read(join(REPO_ROOT, "graphrec_core", "api_keys", "scopes.py"));
    expect(pyStringSet(source, "API_KEY_COMPATIBLE_SCOPES")).toEqual(new Set(API_KEY_SCOPES));
    expect(pyStringSet(source, "ADMIN_DELEGATED_SCOPES")).toEqual(new Set(DELEGATABLE_SCOPES.tenant_administrator));
    expect(pyStringSet(source, "DEVELOPER_DELEGATED_SCOPES")).toEqual(new Set(DELEGATABLE_SCOPES.tenant_developer));
  });
});

/** Exported so a future test can inspect the parsed tables without re-parsing. */
export type { ServerRoute, Route };
