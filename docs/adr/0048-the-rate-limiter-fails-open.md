# ADR 0048 — The rate limiter fails open, and counts the fact that it did

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

§24 asks for rate limits on all five configured classes. Until Phase 16 the five
settings existed, `.env.example` documented them, the `rate_limited` copy string
existed and the 429 mapping existed — and nothing counted a request. That is the
most expensive shape a missing control can take, because everything around it
reads as evidence that it is there.

Implementing it raises one question that is not a detail: what happens when the
counter store is unreachable. Redis holds the counters, Redis is on N1, and
`§9.4 Redis crash` is a failure mode the plan already expects.

**Fail closed** means a cache restart refuses every request on all five limited
routes. Two of those are `/auth/sign-in` and `/platform/auth/sign-in`, so nobody
can sign in — including whoever would have signed in to fix the cache. A
component whose failure escalates to a full outage is a worse component than the
attack it defends against.

**Fail open** means that during a Redis outage there is no rate limiting. The
window is bounded by how long Redis is down, and the exposure is credential
stuffing against Argon2id hashes rather than anything cheap.

## Decision

**Fail open, and emit `graphrec_rate_limit_unavailable_total` plus a warning
every time it happens.** A security control that has silently stopped applying
is worse than one that is failing loudly, so the degradation is a metric an
operator can alert on rather than a silence.

Three further choices, each recorded at the call site:

* **Fixed window, not sliding.** A caller can burst up to `2 × limit` across a
  window boundary. Accepted: the limits here are about grinding attacks and
  runaway integrations, and a sliding window costs a sorted set per caller.
* **Keyed on the caller, never on the route.** Pre-authentication limits key on
  `request.client.host` — never `X-Forwarded-For`, matching what
  `auth.py::_client_address` already does, because a header a client controls is
  not an identity. Post-authentication limits key on `tenant_id`: a console
  behind one office NAT would otherwise share a bucket between every employee.
* **`EXPIRE` on every request, not only the first.** `INCR` on a key with no TTL
  is how a limiter leaks, and an error between the two commands would otherwise
  leave one caller locked out permanently with nothing in the logs.

A limit of `0` means *off*, not *refuse everything*. An unset setting must not
be an outage.

## Consequences

The `login` bucket is shared between the tenant realm and the platform realm for
a given address. That is deliberate — the two sign-in forms are the same attack
surface from one address — and it means a platform operator behind the same NAT
as a tenant under attack is locked out with them.

The suite had to change to accommodate this. `TestClient` reports `testclient`
as the peer, so 1200 tests look to the limiter like one caller trying eight
hundred passwords. The counters are cleared between tests rather than the limits
being widened under `ci`, so the dependency still runs on every request and
still reads the production numbers — it just does not remember the previous
test. Widening the limits in CI would have meant the shipped configuration was
never the configuration under test.

`tests/api/test_rate_limits.py` asserts behaviour *and* walks the route table to
prove each of the five classes is attached to something. The second half is the
one that matters: a limiter with impeccable behaviour and no callers passes
every behavioural test, which is precisely the state this ADR was written to end.
