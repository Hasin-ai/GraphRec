/**
 * The one-file promise, enforced.
 *
 * §10.7 says the design system is not chosen and that swapping it must be a
 * single-file change. That is only true while `tokens.css` is the only place a
 * colour, a radius or a font family is written down — and the way it stops
 * being true is not a redesign, it is one `#eee` typed into a component at half
 * past six on a Friday.
 *
 * So this reads the stylesheets rather than trusting them. It is a lint, and it
 * lives with the tests because a lint nobody runs is a comment.
 *
 * It reads them off disk with `node:fs`. The obvious alternative,
 * `import.meta.glob(..., { query: '?raw' })`, is what this was written with
 * first, and it returned an **empty string for every `.css` file** — Vite
 * resolves a stylesheet through its CSS pipeline before the raw query is
 * honoured. Two of the four assertions below were passing over no input at all,
 * which is the failure mode a lint is least able to survive: it reported
 * success and checked nothing. Reading the bytes is uglier and true.
 */

import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const STYLES = dirname(fileURLToPath(import.meta.url));
const SRC = join(STYLES, '..');
const TOKENS = 'tokens.css';

function read(file: string): string {
  return readFileSync(file, 'utf8');
}

/** Every stylesheet, keyed by bare filename. */
function stylesheets(): Map<string, string> {
  return new Map(
    readdirSync(STYLES)
      .filter((name) => name.endsWith('.css'))
      .map((name) => [name, read(join(STYLES, name))]),
  );
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return entry.isFile() && /\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

/** Strips comments, so a hex quoted in prose is not a violation. */
function code(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

/** First capture group of every match, with the undefineds
    `noUncheckedIndexedAccess` insists on removed — a one-group regex fills it. */
function captures(source: string, pattern: RegExp): string[] {
  return [...source.matchAll(pattern)].flatMap((match) => (match[1] ? [match[1]] : []));
}

function colourLiterals(source: string): string[] {
  const body = code(source);
  return [...(body.match(HEX) ?? []), ...(body.match(FUNCTIONAL_COLOUR) ?? [])];
}

const HEX = /#[0-9a-fA-F]{3,8}\b/g;
const FUNCTIONAL_COLOUR = /\b(?:rgba?|hsla?|oklch|color-mix)\s*\(/g;

describe('the design system is one file', () => {
  it('names no colour outside tokens.css', () => {
    const sheets = stylesheets();
    // The lint is only worth anything if it has input. `?raw` gave it none.
    expect(sheets.size).toBeGreaterThan(1);

    const offenders = [...sheets]
      .filter(([name]) => name !== TOKENS)
      .flatMap(([name, source]) => colourLiterals(source).map((match) => `${name}: ${match}`));

    expect(offenders).toEqual([]);
  });

  it('names no colour in any component', () => {
    // The console has no CSS-in-JS and no inline colours. Layout `style`
    // attributes exist in two places and set only `listStyle`, `margin` and
    // `padding` — none of which a design system swap would change.
    const files = sourceFiles(SRC).filter((file) => !file.endsWith('tokens.test.ts'));
    expect(files.length).toBeGreaterThan(50);

    const offenders = files
      .flatMap((file) =>
        colourLiterals(read(file)).map((match) => `${file.replace(SRC, 'src')}: ${match}`),
      );

    expect(offenders).toEqual([]);
  });

  it('defines every token it references', () => {
    // A `var(--thing)` with no `--thing:` renders as nothing, silently. In a
    // colour that is an invisible element; in a spacing step it is a layout
    // that looks merely cramped, which is worse because nobody files it.
    const sheets = stylesheets();
    const defined = new Set(captures(sheets.get(TOKENS) ?? '', /^\s*(--[\w-]+)\s*:/gm));

    const referenced = new Set(
      [...sheets.values()].flatMap((source) => captures(source, /var\(\s*(--[\w-]+)/g)),
    );

    expect([...referenced].filter((token) => !defined.has(token))).toEqual([]);
  });

  it('defines both themes over the same vocabulary', () => {
    // Comments are stripped first: the file's own header mentions the dark
    // selector in prose, and slicing on that gave a "light block" of nothing
    // and a dark block of everything.
    const tokens = code(stylesheets().get(TOKENS) ?? '');
    const split = tokens.indexOf('[data-theme="dark"]');
    expect(split).toBeGreaterThan(0);
    const light = tokens.slice(0, split);
    const dark = tokens.slice(split);

    const names = (block: string) => new Set(captures(block, /^\s*(--[\w-]+)\s*:/gm));
    const lightNames = names(light);
    const darkNames = names(dark);

    // A token dark defines and light does not is a typo: nothing reads it in
    // the light theme, so nothing reveals it.
    expect([...darkNames].filter((token) => !lightNames.has(token))).toEqual([]);

    // Dark overrides only what has to change — the neutral ramp inverts, but a
    // derived token like `--text-muted` follows it for free. These are the ones
    // that cannot be derived, and a theme missing any of them is a theme that
    // silently keeps a light value on a dark page.
    const mustDiffer = [
      '--color-bg',
      '--color-surface',
      '--color-text',
      '--color-divider',
      '--ok',
      '--warn',
      '--danger',
      '--info',
      '--neu',
    ];
    expect(mustDiffer.filter((token) => !darkNames.has(token))).toEqual([]);
  });
});
