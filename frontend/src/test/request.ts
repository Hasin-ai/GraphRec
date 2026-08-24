/**
 * What a mocked `fetch` was actually asked for.
 *
 * `String(input)` is the obvious spelling and it is wrong for one of the three
 * things `fetch` accepts: `String(new Request('/v1/me'))` is `'[object
 * Object]'`, so a test asserting on the URL passes for every request once the
 * client starts passing a `Request`. Every call site in the suite used
 * `String()` and every one of them happened to be handed a string, which is the
 * kind of correct that stops being correct without anything failing.
 *
 * Narrowed rather than cast: each branch reads the URL off the right property.
 */
export function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

/** The body a mocked `fetch` was given, parsed. Same reasoning as above:
 *  `init.body` is a `BodyInit`, and only one of its many shapes stringifies. */
export function requestBody<T = unknown>(body: BodyInit | null | undefined): T {
  if (typeof body !== 'string') {
    throw new Error(`expected a string body, got ${typeof body}`);
  }
  return JSON.parse(body) as T;
}
