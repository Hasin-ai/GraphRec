import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { ConfigurationError, GraphRec, normaliseTenantId } from '../src/index.js';
import { KEY, TENANT, TENANT_HEX, client } from './support.js';

const repo = fileURLToPath(new URL('../../../', import.meta.url));

describe('tenant identifiers', () => {
  it('accepts the dashed form the console shows and the hex the hostname needs', () => {
    expect(normaliseTenantId(TENANT)).toBe(TENANT_HEX);
    expect(normaliseTenantId(TENANT_HEX)).toBe(TENANT_HEX);
    expect(normaliseTenantId(TENANT.toUpperCase())).toBe(TENANT_HEX);
  });

  it('refuses anything that is not a uuid, rather than building a host that will not resolve', () => {
    expect(() => normaliseTenantId('acme')).toThrow(ConfigurationError);
    expect(() => normaliseTenantId('')).toThrow(ConfigurationError);
  });
});

describe('host resolution', () => {
  it('derives both hosts from the shorthand', () => {
    expect(client().hosts).toEqual({
      control: 'https://api.graphrec.example',
      data: `https://${TENANT_HEX}.serve.graphrec.example`,
    });
  });

  it('takes the two deploy domains independently, because the deploy does', () => {
    // `GRAPHREC_CONSOLE_DOMAIN` and `GRAPHREC_API_DOMAIN` are separate variables
    // in `deploy/n1` and `deploy/n3`; an estate is free to name them unrelatedly.
    const gr = new GraphRec({
      apiKey: KEY,
      tenantId: TENANT,
      consoleDomain: 'console.acme.io',
      apiDomain: 'rec.acme.io',
    });
    expect(gr.hosts).toEqual({
      control: 'https://console.acme.io',
      data: `https://${TENANT_HEX}.rec.acme.io`,
    });
  });

  it('lets a local stack override both with full origins', () => {
    const gr = new GraphRec({
      apiKey: KEY,
      tenantId: TENANT,
      controlUrl: 'http://localhost:8000',
      dataUrl: 'http://localhost:8020',
    });
    expect(gr.hosts).toEqual({ control: 'http://localhost:8000', data: 'http://localhost:8020' });
  });

  it('refuses plaintext to anywhere that is not the loopback', () => {
    expect(
      () => new GraphRec({ apiKey: KEY, tenantId: TENANT, controlUrl: 'http://api.example.com', dataUrl: 'https://x.example.com' }),
    ).toThrow(/must be https/);
  });

  it('refuses a half-configured client rather than guessing the other host', () => {
    // The failure this prevents is the quiet one: a single base URL, and every
    // recommendation call answering 404 because that route is not on that app.
    expect(() => new GraphRec({ apiKey: KEY, tenantId: TENANT, controlUrl: 'https://api.example.com' })).toThrow(
      ConfigurationError,
    );
  });
});

/**
 * Test 2 of `docs/SDK_DESIGN.md` §10 — the host derivation matches the deploy.
 *
 * This is the assertion worth having in the whole file. The data-plane hostname
 * is not a convention the SDK is free to choose: N3's edge reads the tenant out
 * of a specific label position and uses it to name a Docker service. If either
 * end of that changes, every request this SDK makes goes to a host that does not
 * resolve — and no unit test of the SDK against itself would notice, because the
 * SDK would still agree with the SDK.
 */
describe('the data host matches what N3 actually routes on', () => {
  const caddyfile = readFileSync(`${repo}deploy/n3/Caddyfile`, 'utf8');
  const compose = readFileSync(`${repo}graphrec/serving_driver/compose.py`, 'utf8');

  it('puts the tenant hex at the label position the edge reads', () => {
    const upstream = /name\s+"([^"]+)"/.exec(caddyfile);
    expect(upstream, 'no dynamic upstream template in deploy/n3/Caddyfile').not.toBeNull();

    const label = /\{http\.request\.host\.labels\.(\d+)\}/.exec(upstream![1]!);
    expect(label, 'the upstream does not name a host label').not.toBeNull();
    const index = Number(label![1]);

    // Caddy counts labels from the right: for `a.b.c.d`, label 0 is `d`.
    const hostname = new URL(client().hosts.data).hostname;
    const fromRight = hostname.split('.').reverse();
    expect(fromRight[index]).toBe(TENANT_HEX);
  });

  it('produces a hostname that names the tenant’s own Compose project', () => {
    const prefix = /PROJECT_PREFIX\s*=\s*"([^"]+)"/.exec(compose);
    const service = /SERVICE_NAME\s*=\s*"([^"]+)"/.exec(compose);
    expect(prefix, 'PROJECT_PREFIX moved').not.toBeNull();
    expect(service, 'SERVICE_NAME moved').not.toBeNull();

    const upstream = /name\s+"([^"]+)"/.exec(caddyfile)![1]!;
    const resolved = upstream.replace(/\{http\.request\.host\.labels\.\d+\}/, TENANT_HEX);
    expect(resolved).toBe(`${prefix![1]}${TENANT_HEX}-${service![1]}`);
  });

  it('assumes an api domain of exactly the depth the label index implies', () => {
    // `domain: 'graphrec.example'` becomes `<hex>.serve.graphrec.example`. That
    // is only right if the tenant lands at the label index above; a shorthand
    // that produced a different depth would be wrong for every estate at once.
    const index = Number(/\{http\.request\.host\.labels\.(\d+)\}/.exec(caddyfile)![1]);
    const apiDomainLabels = 'serve.graphrec.example'.split('.').length;
    expect(apiDomainLabels).toBe(index);
  });
});
