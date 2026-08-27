import { inspect } from 'node:util';
import { describe, expect, it } from 'vitest';
import { ConfigurationError, Credential } from '../src/index.js';
import { KEY, client, envelope, scripted } from './support.js';

const SECRET = KEY.split('.')[1]!;

/**
 * Test 6 of `docs/SDK_DESIGN.md` §10 — nothing after the separator is ever
 * rendered.
 *
 * The credential's prefix is public — the console prints it, the server logs it
 * as the actor — and everything after the `.` is 256 bits that are shown once and
 * never again. The failure this guards against is silent: nobody notices a
 * credential in a log line until somebody else does. That is why the secret is a
 * `#private` field rather than a documented convention, and why this file exists
 * to keep it one.
 */
describe('the secret is unreachable from anything that renders', () => {
  it('is not in the client’s JSON', () => {
    expect(JSON.stringify(client())).not.toContain(SECRET);
  });

  it('is not in the client’s inspect output, at any depth', () => {
    expect(inspect(client(), { depth: 10 })).not.toContain(SECRET);
  });

  it('is not in a template-literal rendering of the client', () => {
    expect(`${JSON.stringify(client())} ${String(client())}`).not.toContain(SECRET);
  });

  it('is not on any own property, however deep a logger walks', () => {
    // A structured logger does not call `toJSON`; it walks the object. `#secret`
    // is invisible to that walk, which is the whole reason it is `#`.
    const seen = new Set<unknown>();
    const walk = (value: unknown): boolean => {
      if (typeof value === 'string') return value.includes(SECRET);
      if (typeof value !== 'object' || value === null || seen.has(value)) return false;
      seen.add(value);
      return Object.values(value).some(walk);
    };
    expect(walk(client())).toBe(false);
  });

  it('is not in the credential’s own renderings, but the prefix is', () => {
    const credential = new Credential(KEY);
    for (const rendering of [String(credential), JSON.stringify(credential), inspect(credential)]) {
      expect(rendering).not.toContain(SECRET);
      expect(rendering).toContain('gr_live_7Kq4');
    }
  });

  it('is reachable exactly once, by the header that has to carry it', () => {
    expect(new Credential(KEY).authorization).toBe(`Bearer ${KEY}`);
  });

  it('is not echoed by a configuration error about the credential', () => {
    // A message that quotes the value puts it in the one place people paste
    // most freely: a bug report.
    const failure = (() => {
      try {
        new Credential('sk_live_something.secret-looking-value');
      } catch (error) {
        return error as ConfigurationError;
      }
      throw new Error('expected a rejection');
    })();
    expect(failure).toBeInstanceOf(ConfigurationError);
    expect(`${failure.message} ${failure.stack ?? ''}`).not.toContain('secret-looking-value');
  });

  it('is not in an error raised from a failed call', async () => {
    const { fetch } = scripted([{ status: 401, body: envelope('auth', 'invalid_credentials') }]);
    const failure = (await client({}, fetch)
      .recommendations.forCustomer({ requestId: 'r', customerId: 'c' })
      .catch((error: unknown) => error)) as Error;

    const rendered = `${failure.message} ${failure.stack ?? ''} ${JSON.stringify(failure)} ${inspect(failure, { depth: 10 })}`;
    expect(rendered).not.toContain(SECRET);
  });

  it('exposes the prefix deliberately, because support conversations need it', () => {
    expect(client().credentialPrefix).toBe('gr_live_7Kq4');
  });
});

describe('the credential is validated by shape before a request is built', () => {
  it.each([
    ['', 'an empty string'],
    ['gr_live_7Kq4', 'no separator'],
    ['gr_live_7Kq4.', 'nothing after the separator'],
    ['live_7Kq4.secret', 'the wrong namespace'],
    ['grk_live_7Kq4.secret', 'the prefix the /integration page prints, which is wrong'],
  ])('refuses %s (%s)', (value) => {
    expect(() => new Credential(value)).toThrow(ConfigurationError);
  });
});
