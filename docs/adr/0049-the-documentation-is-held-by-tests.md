# ADR 0049 — The operational documentation is held by tests

**Status:** Accepted
**Phase:** 16
**Date:** 2026-08-24

## Context

Phase 16 produces documents that make claims about the system: `RUNBOOKS.md`
says which alert leads where, `PRODUCTION_READINESS.md` walks §24 box by box,
`.env.example` lists what can be configured, `frontend/openapi.json` states the
contract, and the `/integration` page tells customers how to call it.

Every one of these is read at the worst possible moment — during an incident, or
by somebody integrating who has no other source. And every one of them decays in
the same silent way: the code changes, the document does not, and nothing
anywhere goes red. A stale runbook is worse than no runbook, because the person
reading it at 3am believes it.

Writing them is cheap. Keeping them true is the whole problem.

## Decision

**Every operational document has a test that fails when it stops being true**,
and the test asserts the relationship, not the prose.

| Document | Held by | What goes red |
|---|---|---|
| `RUNBOOKS.md` | `tests/observability/test_runbooks.py` | An alert with no section, or a section for an alert that no longer exists — both directions. |
| `frontend/openapi.json` | `tests/contract/test_openapi_document.py` | The file is not byte-for-byte what the generator produces today. |
| `/integration` page | `Integration.test.tsx` | A row whose path, method, host, request field or response field disagrees with the document. |
| `.env.example` | `tests/contract/test_env_example.py` | A setting missing from the file, or a line naming no setting — both directions. |
| §9.4 failure table | `tests/drills/test_failure_posture.py` | A failure mode with neither a drill nor a written reason; a drill naming a test that has been renamed; a reason not repeated in `PRODUCTION_READINESS.md`. |
| Alert thresholds | `tests/observability/test_alert_rules.py` | A threshold that disagrees with the number in the plan, or a dashboard threshold that disagrees with the alert. |

Two rules make these worth having.

**Both directions, always.** A one-way check catches the addition and misses the
deletion, and the deletion is the more dangerous of the two: a runbook section
for an alert that no longer fires sends somebody to investigate a thing that
cannot happen.

**A floor test under every parser.** Each of these reads a document with a regex
or a parse, and a parse that silently matches nothing makes every assertion
above it pass vacuously. So each file has one test asserting the parse found
something plausible — `len(documented) > 50`, `len(failures) >= 9`,
`ENDPOINTS.length >= 6`. That test exists because an empty parse is a realistic
merge outcome, not a hypothetical one.

## Consequences

The prose stays hand-written. None of these generates a document from code —
generated prose is not read, and the `/integration` page in particular is
written for a person. What is asserted is the part a machine can own: paths,
methods, hosts, field names, thresholds, cross-references. Judgement stays in
the text.

Documentation changes now break builds, which is the point and is also friction:
renaming a test function breaks the §9.4 ledger, and adding a setting breaks the
build until `.env.example` gains a line. Both are one-line fixes, and both are
changes that would otherwise have shipped as quiet decay.

These tests are load-bearing enough to need their own care. The accessibility
lint in ADR 0039 went vacuous twice while being written, which is the reason the
floor tests above are a rule rather than a habit.

What is *not* covered: the truth of the prose itself. Nothing asserts that the
steps in `#restore-from-backup` work — that is what `restore_drill.sh` on a
timer is for, and it is a different kind of check. The tests here prove the
documents are consistent with the code; only the drill proves a procedure runs.
