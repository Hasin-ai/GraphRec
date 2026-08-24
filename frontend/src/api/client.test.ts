import { beforeEach, describe, expect, it, vi } from 'vitest';
import { anonymous, tenantApi } from './client';
import { hasSession, readAccessToken, resetSessionsForTest, store } from './session';
import { isApiError } from './errors';
import { requestUrl } from '../test/request';

const SESSION = {
  access_token: 'access-1',
  expires_at: '2026-01-01T00:15:00Z',
  refresh_token: 'refresh-1',
  refresh_expires_at: '2026-01-08T00:00:00Z',
};

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

function envelope(code: string, reason = 'Refused.') {
  return {
    error: {
      class: 'auth',
      code,
      reason,
      reference: 'err-0001-aaaaa',
      field_errors: [],
      retryable: false,
      retry_after_seconds: null,
    },
  };
}

function calls(): [string, RequestInit][] {
  return vi.mocked(globalThis.fetch).mock.calls as unknown as [string, RequestInit][];
}

function header(init: RequestInit, name: string): string | null {
  return new Headers(init.headers).get(name);
}

beforeEach(() => {
  resetSessionsForTest();
  window.sessionStorage.clear();
  vi.stubGlobal('fetch', vi.fn());
});

describe('the API client', () => {
  it('attaches the access token as a bearer', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, { ok: true }));

    await tenantApi.get('/v1/me');

    expect(header(calls()[0]![1], 'Authorization')).toBe('Bearer access-1');
  });

  it('never sends a tenant identifier of its own', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, { ok: true }));

    await tenantApi.get('/v1/products');

    // NR-NF-02: the tenant is resolved from the credential, server-side. A
    // header or a query parameter naming it would be an input a handler could
    // be tricked into trusting, so the console must not offer one at all.
    const [url, init] = calls()[0]!;
    const sent = new Headers(init.headers);
    expect([...sent.keys()].map((key) => key.toLowerCase())).not.toContain('x-tenant-id');
    expect(url).not.toContain('tenant_id');
  });

  it('refreshes once on a 401 and replays the original request', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(json(401, envelope('invalid_credentials')))
      .mockResolvedValueOnce(json(200, { ...SESSION, access_token: 'access-2' }))
      .mockResolvedValueOnce(json(200, { ok: true }));

    await expect(tenantApi.get('/v1/me')).resolves.toEqual({ ok: true });

    const sent = calls();
    expect(sent).toHaveLength(3);
    expect(sent[1]![0]).toBe('/v1/auth/refresh');
    // The replay carries the *new* token, not the one that was just refused.
    expect(header(sent[2]![1], 'Authorization')).toBe('Bearer access-2');
    expect(readAccessToken('tenant')).toBe('access-2');
  });

  it('gives up and clears the session when the replay is refused too', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(json(401, envelope('invalid_credentials')))
      .mockResolvedValueOnce(json(200, { ...SESSION, access_token: 'access-2' }))
      .mockResolvedValueOnce(json(401, envelope('invalid_credentials')));

    await expect(tenantApi.get('/v1/me')).rejects.toThrow();

    // Exactly one refresh. A client that retried the refresh would present a
    // rotated token twice, which the backend reads as theft.
    expect(calls().filter(([url]) => url === '/v1/auth/refresh')).toHaveLength(1);
    expect(hasSession('tenant')).toBe(false);
  });

  it('sends one refresh for concurrent requests that all find the token stale', async () => {
    store('tenant', SESSION);
    const fetchMock = vi.mocked(globalThis.fetch);
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/v1/auth/refresh') return json(200, { ...SESSION, access_token: 'access-2' });
      return json(401, envelope('invalid_credentials'));
    });

    await Promise.allSettled([
      tenantApi.get('/v1/me'),
      tenantApi.get('/v1/products'),
      tenantApi.get('/v1/credentials'),
    ]);

    expect(calls().filter(([url]) => url === '/v1/auth/refresh')).toHaveLength(1);
  });

  it('captures X-Request-Id as the reference when the body carries none', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response('<html>gateway timeout</html>', {
        status: 504,
        headers: { 'X-Request-Id': 'req-77' },
      }),
    );

    try {
      await anonymous('/v1/auth/sign-in', {});
      expect.unreachable('the 504 should have thrown');
    } catch (error) {
      expect(isApiError(error)).toBe(true);
      if (isApiError(error)) expect(error.reference).toBe('req-77');
    }
  });

  it('presents an unreachable network as an envelope rather than a TypeError', async () => {
    vi.mocked(globalThis.fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'));

    try {
      await anonymous('/v1/auth/sign-in', {});
      expect.unreachable('the network failure should have thrown');
    } catch (error) {
      expect(isApiError(error)).toBe(true);
      if (isApiError(error)) expect(error.code).toBe('network_unreachable');
    }
  });

  it('sends no Authorization header on the anonymous exchanges', async () => {
    store('tenant', SESSION);
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(json(200, SESSION));

    await anonymous('/v1/auth/sign-in', { tenant_code: 'acme' });

    expect(header(calls()[0]![1], 'Authorization')).toBeNull();
  });
});
