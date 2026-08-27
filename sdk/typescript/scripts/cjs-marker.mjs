// `dist/cjs/*.js` is CommonJS, and this package is `"type": "module"`.
//
// Node resolves a file's module system from the nearest `package.json`, so
// without this marker every emitted `require(...)` in `dist/cjs` is parsed as
// ESM and throws ReferenceError on the first line. One file, written by the
// build rather than checked in, because a checked-in file inside `dist` is a
// file `rm -rf dist` deletes and nobody notices until publish.
import { writeFileSync } from 'node:fs';

writeFileSync(
  new URL('../dist/cjs/package.json', import.meta.url),
  `${JSON.stringify({ type: 'commonjs' }, null, 2)}\n`,
);
