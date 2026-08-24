# ADR 0034 — The console stays on the Modernist tokens, and the swap stays one file

**Status:** Accepted (provisional — see Consequences)
**Phase:** 14
**Date:** 2026-08-24

## Context

Two design systems are specified for the same console. The prototype is bound to
a "Modernist" system, with semantic state colours (`--ok / --warn / --danger /
--info / --neu`) defined alongside it. `FRONTEND_BUILD_PROMPT.md §11` specifies
a different Claude palette. The folder holding the prototype is literally named
`Design system decision pending`.

`docs/BUILD_PROMPT.md` §10.7 says: *"Do not resolve this yourself… Ask which
system to use before Phase 14; until then use the Modernist tokens the prototype
already renders with, so screenshots stay comparable."*

The question was raised at the top of Phase 13 and again at the top of Phase 14
and has not been answered. §10.7 anticipates exactly this and states what to do
in the meantime, so the instruction is treated as the answer for now — recorded
here as a decision taken by instruction rather than by preference, which is the
only honest way to record it.

## Decision

**Build on the Modernist tokens.** `styles/tokens.css` is the one file that
names a colour, a radius, a spacing step or a font. Nothing else in the console
does, in either theme.

**Both themes are fully token-defined**, so a swap does not leave dark mode
half-converted — which is the failure mode of a design-system change made under
time pressure.

**The swap is one file.** This is the property being protected, not the palette.
The token names are semantic (`--ok`, `--text-muted`, `--border-hairline`) and
never descriptive (`--green`, `--grey-600`), because a system swapped onto
descriptive names either renames every call site or ships a `--green` that is
not green.

A check runs over `src/**/*.tsx` and `src/**/*.css` confirming that no literal
colour, `px` radius or font stack appears outside `tokens.css`.

## Consequences

If the Claude palette is chosen later, the change is `tokens.css` and nothing
else, in both themes at once. That is the whole point of having spent Phase 13
on tokens before there was anything to style.

Screenshots taken now stay comparable with the prototype, which is what §10.7
asks for and what makes a visual diff meaningful while the question is open.

This ADR is **provisional**. If the answer arrives and it is the Claude palette,
this ADR is superseded rather than amended: the decision recorded here is "we
proceeded on the standing instruction", and that remains true even after the
instruction is replaced.
