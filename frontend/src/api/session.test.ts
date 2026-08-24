import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearSession,
  hasSession,
  readAccessToken,
  readRefreshToken,
  resetSessionsForTest,
  store,
} from './session';

/**
 * jsdom's `localStorage` is shadowed by Node's own experimental global, which
 * is `undefined` unless the process was started with `--localstorage-file`.
 * Rather than skip the assertion that matters most here, the tests install a
 * recording stub: anything written to `localStorage` lands in `written` and
 * fails the test that put it there.
 */
const written = new Map<string, string>();

function installLocalStorageSpy(): void {
  written.clear();
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => written.get(key) ?? null,
      setItem: (key: string, value: string) => written.set(key, value),
      removeItem: (key: string) => written.delete(key),
      clear: () => written.clear(),
      key: (index: number) => [...written.keys()][index] ?? null,
      get length() {
        return written.size;
      },
    },
  });
}

const RESPONSE = {
  access_token: 'access-abc',
  expires_at: '2026-01-01T00:15:00Z',
  refresh_token: 'refresh-xyz',
  refresh_expires_at: '2026-01-08T00:00:00Z',
};

beforeEach(() => {
  installLocalStorageSpy();
  resetSessionsForTest();
  window.sessionStorage.clear();
});

describe('the session store', () => {
  it('keeps the access token in memory and nowhere a document can be read from', () => {
    store('tenant', RESPONSE);

    expect(readAccessToken('tenant')).toBe('access-abc');

    // §10.3, the whole rule: the access token is the bearer credential, and it
    // must not survive in any storage a later script or an XSS payload can read
    // at leisure. Asserting on the serialised contents rather than on a key
    // name catches it being smuggled inside some other value.
    expect(JSON.stringify(window.sessionStorage)).not.toContain('access-abc');
    expect([...written.values()].join('|')).not.toContain('access-abc');
  });

  it('never writes anything at all to localStorage', () => {
    store('tenant', RESPONSE);
    store('platform', RESPONSE);
    expect([...written.keys()]).toEqual([]);
  });

  it('puts the refresh token in sessionStorage so a reload survives but a new tab does not', () => {
    store('tenant', RESPONSE);
    expect(readRefreshToken('tenant')).toBe('refresh-xyz');
    expect(JSON.stringify(window.sessionStorage)).toContain('refresh-xyz');
  });

  it('treats a refresh token with no access token as a session', () => {
    store('tenant', RESPONSE);
    // What a reloaded tab looks like: memory is gone, storage is not.
    resetSessionsForTest();
    window.sessionStorage.setItem(
      'graphrec.refresh.tenant',
      JSON.stringify({ refreshToken: 'refresh-xyz', refreshExpiresAt: RESPONSE.refresh_expires_at }),
    );

    expect(readAccessToken('tenant')).toBeNull();
    expect(hasSession('tenant')).toBe(true);
  });

  it('keeps the two realms apart', () => {
    store('tenant', RESPONSE);
    expect(hasSession('platform')).toBe(false);

    clearSession('tenant');
    store('platform', { ...RESPONSE, access_token: 'platform-access' });
    expect(readAccessToken('tenant')).toBeNull();
    expect(readAccessToken('platform')).toBe('platform-access');
  });

  it('forgets both halves on clear', () => {
    store('tenant', RESPONSE);
    clearSession('tenant');

    expect(hasSession('tenant')).toBe(false);
    expect(readRefreshToken('tenant')).toBeNull();
    expect(JSON.stringify(window.sessionStorage)).not.toContain('refresh-xyz');
  });

  it('reads a corrupted entry as no session rather than as a broken one', () => {
    window.sessionStorage.setItem('graphrec.refresh.tenant', '{not json');
    expect(hasSession('tenant')).toBe(false);
    expect(readRefreshToken('tenant')).toBeNull();
  });
});
