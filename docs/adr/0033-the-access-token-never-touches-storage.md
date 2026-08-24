# ADR 0033 — The access token lives in memory; only the refresh token is stored

**Status:** Accepted
**Phase:** 13
**Date:** 2026-08-24

## Context

The console holds two tokens per realm: a short-lived access token sent as a
bearer on every request, and a long-lived rotating refresh token used to mint
new access tokens. Where they live decides what an injected script can steal.

`docs/BUILD_PROMPT.md` §10.3 is explicit — access token in memory only, refresh
token in `sessionStorage` with the trade-off documented, **never**
`localStorage`. This ADR records the reasoning so the constraint survives
someone finding it inconvenient.

## Decision

**Access token: a module-level `Map`, cleared by a page reload.**

Not React state: `client.ts` reads it from outside the component tree, and a
route loader runs before anything has mounted. A `useContext` here would mean
loaders could not authenticate.

**Refresh token: `sessionStorage`, per realm, under a named key.**

`sessionStorage` is scoped to one tab and dies with it. That is the trade-off
being accepted: a reload keeps the session (the client exchanges the refresh
token for a new access token on the first request), a new tab does not, and
closing the tab ends it. The alternative that survives a new tab is
`localStorage`, which also survives everything else — including the attacker
who arrives tomorrow.

**Neither token is ever written to `localStorage`, for any purpose.** The only
thing the console persists there is the theme.

**One refresh in flight per realm, shared.** Refresh tokens are single-use and
rotate. A page that fires six queries on mount and finds the token expired would
otherwise send six refreshes, five of them presenting a token the first has
already superseded — which the backend correctly reads as evidence of theft and
answers by revoking the family. Without deduplication the console signs itself
out by being busy.

**One retry, then stop.** A 401 triggers exactly one refresh-and-replay. A
second 401 clears the session and routes to `/login`. Retrying the refresh would
present a rotated token twice, which is the theft signal again.

## Consequences

An XSS payload can still read the access token out of memory while it runs —
this buys nothing against a live attacker with script execution. What it buys is
that nothing usable is left behind for a script that runs *later*, on a machine
where somebody used the console yesterday and closed the tab.

Two tabs of the same console share one `sessionStorage` only if one was opened
from the other; otherwise each signs in separately. That is a real inconvenience
and it is the accepted cost.

Three tests pin the rule: the serialised contents of both storages are asserted
not to contain the access token (rather than asserting on key names, which a
rename would defeat), `localStorage` is a recording stub that fails any test
writing to it, and the refresh path asserts that concurrent requests produce
exactly one refresh call.
