# ADR 0003 — Generated vocabularies are pinned, not merely regenerated

**Status:** Accepted
**Phase:** 1
**Date:** 2026-08-22

## Context

BUILD_PROMPT calls the console prototype an executable specification: its enum
values are requirements. `scripts/gen_enums.py` makes that literal by parsing the
prototype's `GROUPS`, `JOB_STAGES`, `SCOPES` and `PERMS` tables and emitting both
`graphrec/common/enums.py` and `frontend/src/lib/enums.ts`, with a `--check` mode
in CI that fails on any divergence.

Regeneration alone turned out to be a weaker guarantee than it appears.
Deliberately injecting five kinds of drift into the prototype showed the generator
detecting only three. A **renamed** badge value and a **dropped** job stage both
regenerated cleanly and silently: the generator faithfully reproduced the new
prototype, and the diff looked like an intentional change. The check answers "do
the two artefacts agree?" — not "is the vocabulary still the one the SRS
specifies?".

For a stage rail, a reorder is equally invisible and equally wrong: `JOB_STAGES`
is a sequence, and its order is the pipeline.

## Decision

Pin the expected membership alongside the generator:

- `LOCKED_VOCABULARIES` — the exact value set for each badge group.
- `LOCKED_JOB_STAGES` — the exact ordered tuple of stages.

`load_vocabulary()` compares the parsed prototype against these and fails with a
message naming the added, removed or reordered values. Changing a vocabulary now
requires editing the lock as a separate, reviewable act.

Re-testing against seven drift scenarios — including the two that previously
slipped through and a stage reordering — detected all seven.

## Consequences

- Every legitimate vocabulary change costs one extra edit. That edit is the
  review, and it is the point.
- The locks encode D8's seven model states, which remain provisional. The lock
  comment records where the other three lifecycle values actually live:
  `TRAINING`, `EVALUATED` and `FAILED` stay inside the training job, and
  `DEPLOYING` is `model_deployments.state = 'progressing'`.
- Totals are asserted against BUILD_PROMPT §6: 7 badge groups totalling 42 values
  (12+7+6+5+4+4+4), 9 job stages, 5 scopes, 5 permissions.
