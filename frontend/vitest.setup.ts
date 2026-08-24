import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

/**
 * Node's `Request` refuses the `AbortSignal` this jsdom realm produces.
 *
 * The two are nominally the same class — `instanceof` agrees — but undici's
 * internal brand check does not, so `new Request(url, { signal })` throws.
 * React Router constructs exactly that for every client-side navigation, which
 * means without this shim *every* navigation in a test fails with an error that
 * says nothing about routing.
 *
 * The shim drops the caller's signal and lets `Request` mint its own. The cost
 * is that a loader cannot be cancelled mid-navigation under test; nothing here
 * depends on that, and the alternative is to not test navigation at all.
 *
 * It is applied only if the platform actually has the defect, so it disappears
 * on its own when the underlying bug is fixed.
 */
function installRequestSignalShim(): void {
  const NativeRequest = globalThis.Request;
  try {
    new NativeRequest('http://localhost/', { signal: new AbortController().signal });
    return;
  } catch {
    // Defect present — fall through and patch.
  }

  class CompatRequest extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      if (init && 'signal' in init) {
        const { signal: _incompatible, ...rest } = init;
        super(input, rest);
      } else {
        super(input, init);
      }
    }
  }

  globalThis.Request = CompatRequest;
}

installRequestSignalShim();

afterEach(cleanup);
