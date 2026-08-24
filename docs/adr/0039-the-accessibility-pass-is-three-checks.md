# ADR 0039 — The accessibility pass is three checks, because one would be a lie

**Status:** Accepted
**Phase:** 15
**Date:** 2026-08-24

## Context

§13 rule 10: every interactive element is keyboard reachable with a visible
focus state, and dialogs trap focus. Rule 9: both themes fully token-defined.

The obvious implementation is to run axe over each page and call it done. That
would have passed, and it would have been worth much less than it looked:

* **axe cannot see focus behaviour.** It checks that `aria-modal` is set, which
  is the easy half of a modal. Tab cycling and focus restoration — the half a
  keyboard user actually needs — are invisible to it.
* **axe cannot see colour in jsdom.** No CSS is applied and no layout is
  computed, so every element resolves to transparent on transparent and
  `color-contrast` reports *incomplete*, which is neither a pass nor a fail. A
  suite that left the rule enabled would show a green tick over a check that
  never ran.

## Decision

**Three checks, in `src/a11y.test.tsx`, each covering what the others cannot.**

1. **axe over a rendered page from each of the four shells**, plus one with a
   dialog open — run against the real route table with real loaders, so the
   markup under test is the markup that ships. `color-contrast` is explicitly
   disabled with the reason written at the call site.
2. **The focus trap, driven by keyboard.** Focus enters on open; Tab and
   Shift+Tab stay inside; Escape returns focus to whatever opened the dialog.
   The Tab test rounds the ring twice, because a trap that only wraps the last
   element passes a single pass and leaks on the second.
3. **The stylesheets, read as text.** A visible focus ring is a stylesheet
   fact, so it is checked as one: `:focus-visible` exists, and no block removes
   an outline without putting a `box-shadow` or another outline back.

**`axe-core` is a dev dependency.** Hand-rolled rules would have caught the
things already thought of, which is the wrong half.

## Consequences

The third check is a text lint, and text lints go vacuous quietly. This one
went vacuous **twice** while being written — once because `\s*` before a
negative lookahead backtracks to zero width and matched the space in
`outline: none`, and once because the selector's own colon (`:focus`) was read
as a declaration separator. Both versions reported success over a deliberately
planted violation.

So the rule is a function, and there is a test that feeds it five literals —
two that must be flagged, three that must not. That test is the reason the lint
cannot go quiet again without something going red.

Contrast between the two themes remains unproven by machine. `tokens.test.ts`
proves both themes define the same vocabulary and that the nine tokens which
cannot be derived are overridden; it does not prove the resulting pairs pass
WCAG. That needs a browser, and it belongs with the visual work in Phase 16.
