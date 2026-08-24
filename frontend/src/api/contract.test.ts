/**
 * Every URL this console builds is a URL the server serves.
 *
 * The console's *types* are generated from `openapi.json`, so a wrong shape is
 * a compile error. Its *paths* are template strings, and a template string is
 * not checked by anything — `tsc` is perfectly happy with
 * `/v1/platform/tenants/${id}:change-status` against a server that only offers
 * `:status`. That mistake shipped in Phase 15 on two endpoints and was invisible
 * to 112 passing tests, because every one of them mocked `fetch` and answered
 * whatever was asked.
 *
 * This is the §24 line "OpenAPI published and matching `/integration`'s
 * documented shapes", read as a check rather than a promise: the document is
 * the published contract, and the console is held to it here.
 *
 * The method matters as much as the path. A `POST` to a path that exists but
 * only accepts `GET` is a 405, and a test that compared paths alone would pass.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const HOOKS = join(HERE, 'hooks');

type OpenApi = { paths: Record<string, Record<string, unknown>> };

const document = JSON.parse(
  readFileSync(join(HERE, '..', '..', 'openapi.json'), 'utf8'),
) as OpenApi;

/**
 * A document path with its parameters blanked: `/v1/products/{product_id}`
 * becomes `/v1/products/*`.
 *
 * Reduced rather than parsed, because the console builds paths with template
 * literals and there is no way to recover a parameter's *name* from one — nor
 * any reason to. The server does not care what the console calls it.
 */
function documentShape(path: string): string {
  return path.replace(/\{[^}]+\}/g, '*');
}

/**
 * The same reduction applied to a template literal from the source.
 *
 * Scanned rather than regexed. `\`/v1/platform/tenants${suffix ? \`?${suffix}\` : ''}\``
 * contains a nested template literal, a quote and a brace, and every regex that
 * looks like it handles that is one that stops at the wrong character and
 * silently reports a path nobody wrote. So the braces are counted.
 *
 * A trailing `*` not preceded by `/` is dropped: that is the query-suffix
 * idiom above, and a query string is the console's business, not the
 * document's.
 */
export function templateShape(raw: string): string {
  let out = '';
  let depth = 0;
  for (let i = 0; i < raw.length; i += 1) {
    if (depth === 0 && raw[i] === '$' && raw[i + 1] === '{') {
      depth = 1;
      out += '*';
      i += 1;
      continue;
    }
    if (depth > 0) {
      if (raw[i] === '{') depth += 1;
      else if (raw[i] === '}') depth -= 1;
      continue;
    }
    out += raw[i];
  }
  const withoutQuery = out.split('?')[0]!;
  return withoutQuery.endsWith('*') && !withoutQuery.endsWith('/*')
    ? withoutQuery.slice(0, -1)
    : withoutQuery;
}

const served = new Map<string, Set<string>>();
for (const [path, operations] of Object.entries(document.paths)) {
  const key = documentShape(path);
  const methods = served.get(key) ?? new Set<string>();
  for (const method of Object.keys(operations)) methods.add(method.toUpperCase());
  served.set(key, methods);
}

/**
 * Every `api.<method>(...)` call in the hook layer, as (method, path) pairs.
 *
 * Read from source rather than by executing the hooks: a call site is what has
 * to be right, and exercising them would need a session, a query client and a
 * server. The scanner below finds the helper call and then reads its first
 * argument as a string or template literal, counting braces, so a nested
 * template does not truncate the path.
 *
 * The `finds the calls` test asserts a floor on how many it found, so a rename
 * that makes this match nothing fails rather than passing over an empty list.
 */
function callSites(): { file: string; method: string; path: string }[] {
  const found: { file: string; method: string; path: string }[] = [];
  const opener = /\b\w*[Aa]pi\.(get|post|patch|put|del|delete)\s*(?:<[^>]*>)?\s*\(\s*(['"`])/g;
  for (const file of readdirSync(HOOKS)) {
    if (!file.endsWith('.ts')) continue;
    const source = readFileSync(join(HOOKS, file), 'utf8');
    for (const match of source.matchAll(opener)) {
      const quote = match[2]!;
      const start = match.index + match[0].length;
      const raw = readLiteral(source, start, quote);
      if (raw === null) continue;
      const method = match[1]!.toUpperCase();
      found.push({
        file,
        method: method === 'DEL' ? 'DELETE' : method,
        path: templateShape(raw),
      });
    }
  }
  return found;
}

/** The literal's body, from just after its opening quote to its closing one. */
function readLiteral(source: string, start: number, quote: string): string | null {
  let depth = 0;
  for (let i = start; i < source.length; i += 1) {
    const char = source[i];
    if (char === '\\') {
      i += 1;
      continue;
    }
    if (quote === '`') {
      if (char === '$' && source[i + 1] === '{') {
        depth += 1;
        i += 1;
        continue;
      }
      if (depth > 0) {
        if (char === '{') depth += 1;
        else if (char === '}') depth -= 1;
        continue;
      }
    }
    if (char === quote && depth === 0) return source.slice(start, i);
    if (char === '\n' && quote !== '`') return null;
  }
  return null;
}

describe('the console and the published document', () => {
  const sites = callSites();

  it('finds the calls it is supposed to be checking', () => {
    // Without this, a refactor that renamed the client helpers would turn every
    // assertion below into a loop over an empty array — a green test that
    // checks nothing, which is the outcome this whole file exists to prevent.
    expect(sites.length).toBeGreaterThan(20);
    const files = new Set(sites.map((site) => site.file));
    expect(files).toContain('platform.ts');
    expect(files).toContain('catalogue.ts');
  });

  it('calls no path the server does not serve', () => {
    const unknown = sites.filter((site) => !served.has(site.path));
    expect(unknown.map((site) => `${site.file}: ${site.method} ${site.path}`)).toEqual([]);
  });

  it('calls every path with a method it accepts', () => {
    const wrong = sites.filter(
      (site) => served.has(site.path) && !served.get(site.path)!.has(site.method),
    );
    expect(
      wrong.map(
        (site) =>
          `${site.file}: ${site.method} ${site.path} (server accepts ${[
            ...served.get(site.path)!,
          ].join(', ')})`,
      ),
    ).toEqual([]);
  });

  it('sends no tenant identifier in any path', () => {
    // NR-NF-02 and §13. Asserted against the document too, not only the
    // console: if a route ever grew a tenant segment, the console would be
    // free to send one and this file would have blessed it.
    const tenantScoped = Object.keys(document.paths).filter(
      (path) => /\{tenant_id\}/.test(path) && !path.startsWith('/v1/platform/'),
    );
    expect(tenantScoped).toEqual([]);
  });
});
