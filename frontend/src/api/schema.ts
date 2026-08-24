/**
 * The generated schemas, under one name.
 *
 * Every response type in `hooks/` is `S['SomethingResponse']` rather than a
 * hand-written interface. That is the whole point of generating the client: a
 * field the backend renames breaks compilation here instead of rendering
 * `undefined` in a table, and a field the backend adds needs no work at all.
 *
 * Regenerate with `npm run gen:client`; `npm run gen:client:check` fails the
 * build if this file's source has drifted from the API.
 */

import type { components } from './types.gen';

export type S = components['schemas'];
