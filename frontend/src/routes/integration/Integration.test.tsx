/**
 * The `/integration` page is the API documentation, so it is held to the API.
 *
 * BACKEND_PLAN §24 asks for "OpenAPI published and matching `/integration`'s
 * documented shapes". `src/api/contract.test.ts` checks the calls the console
 * *makes*; this checks the calls the console *tells a customer to make*, which
 * is the more dangerous of the two. A wrong path in the console breaks the
 * console and somebody notices within a day. A wrong path on this page is
 * copied into a customer's own service, and the person debugging it does not
 * have the OpenAPI document open.
 *
 * The page is deliberately not generated from `openapi.json`. Its prose is
 * written for a reader and a generated table is not, so what is asserted is the
 * part a machine can own — path, method, scope — and the prose stays hand
 * written.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ENDPOINTS } from './Integration';

const HERE = dirname(fileURLToPath(import.meta.url));

type Schema = {
  $ref?: string;
  properties?: Record<string, unknown>;
  required?: string[];
};

type Operation = {
  servers?: { url: string }[];
  requestBody?: { content: Record<string, { schema: Schema }> };
  responses: Record<string, { content?: Record<string, { schema: Schema }> }>;
};

type OpenApi = {
  paths: Record<string, Record<string, Operation>>;
  components: { schemas: Record<string, Schema> };
};

const document = JSON.parse(
  readFileSync(join(HERE, '..', '..', '..', 'openapi.json'), 'utf8'),
) as OpenApi;

/** Follow one `$ref`. The bodies on this page are objects, never `anyOf` unions. */
function resolve(schema: Schema | undefined): Schema | undefined {
  if (schema?.$ref === undefined) return schema;
  return document.components.schemas[schema.$ref.replace('#/components/schemas/', '')];
}

function operationOf(endpoint: (typeof ENDPOINTS)[number]): Operation {
  const operation = document.paths[endpoint.path]?.[endpoint.method.toLowerCase()];
  if (operation === undefined) {
    throw new Error(`${endpoint.method} ${endpoint.path} is not in openapi.json`);
  }
  return operation;
}

/**
 * The snippets are written for a reader, so a few carry `/* as above *\/`
 * where repeating a block would be noise. Strip those and they are JSON — the
 * `…` placeholders sit inside strings and parse fine.
 */
function example(snippet: string): Record<string, unknown> {
  return JSON.parse(snippet.replace(/\/\*[\s\S]*?\*\//g, 'null')) as Record<string, unknown>;
}

function successBody(operation: Operation): Schema | undefined {
  const status = Object.keys(operation.responses).find((code) => code.startsWith('2'));
  if (status === undefined) return undefined;
  return resolve(operation.responses[status]?.content?.['application/json']?.schema);
}

describe('the endpoints /integration documents', () => {
  it('documents something', () => {
    // A floor. The rest of this file passes vacuously against an empty table,
    // and an empty table is a plausible outcome of a refactor.
    expect(ENDPOINTS.length).toBeGreaterThanOrEqual(6);
  });

  it('names only paths the server serves', () => {
    const served = new Set(Object.keys(document.paths));
    for (const endpoint of ENDPOINTS) {
      expect(served, `${endpoint.method} ${endpoint.path}`).toContain(endpoint.path);
    }
  });

  it('names a method each path accepts', () => {
    for (const endpoint of ENDPOINTS) {
      const operations = document.paths[endpoint.path] ?? {};
      expect(
        Object.keys(operations),
        `${endpoint.path} does not accept ${endpoint.method}`,
      ).toContain(endpoint.method.toLowerCase());
    }
  });

  it('sends each call to the host that answers it', () => {
    // The reason this is asserted rather than trusted: N3 routes on the
    // hostname, so a data-plane call sent to the control-plane host does not
    // fail loudly with "wrong tenant" — it 404s, and the page is the only
    // place a customer would look to find out why.
    for (const endpoint of ENDPOINTS) {
      const url = operationOf(endpoint).servers?.[0]?.url ?? '';
      const expected = endpoint.host === 'data' ? '{tenant}' : '{console_domain}';
      expect(url, `${endpoint.method} ${endpoint.path}`).toContain(expected);
    }
  });

  it('shows request bodies the server would accept', () => {
    for (const endpoint of ENDPOINTS) {
      if (endpoint.request === undefined) continue;
      const label = `${endpoint.method} ${endpoint.path} request`;
      const schema = resolve(
        operationOf(endpoint).requestBody?.content['application/json']?.schema,
      );
      expect(schema?.properties, label).toBeDefined();
      const documented = Object.keys(schema?.properties ?? {});
      const shown = Object.keys(example(endpoint.request));

      // No field the server does not have. Copying an example that carries an
      // unknown key is how somebody spends an afternoon on a 422.
      for (const field of shown) expect(documented, `${label}: ${field}`).toContain(field);
      // And nothing required left out, for the same reason in reverse.
      for (const field of schema?.required ?? []) expect(shown, `${label}: ${field}`).toContain(field);
    }
  });

  it('shows responses the server would send', () => {
    for (const endpoint of ENDPOINTS) {
      const label = `${endpoint.method} ${endpoint.path} response`;
      const schema = successBody(operationOf(endpoint));
      expect(schema?.properties, label).toBeDefined();
      const documented = Object.keys(schema?.properties ?? {});
      for (const field of Object.keys(example(endpoint.response))) {
        expect(documented, `${label}: ${field}`).toContain(field);
      }
    }
  });

  it('documents only the data plane', () => {
    // The page describes what a customer's *service* calls with an API key.
    // A control-plane path here would be an instruction to send a session
    // token from a backend that does not have one.
    for (const endpoint of ENDPOINTS) {
      expect(endpoint.path.startsWith('/v1/platform/')).toBe(false);
    }
  });
});
