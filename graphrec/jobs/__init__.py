"""The job queue.

PostgreSQL is the broker (D2, ADR 0011). One table, one claim function, and a
lease that expires — which between them give at-least-once delivery, fair
sharing across tenants, and automatic recovery from a worker that dies without
saying so.

The pieces:

* `states`   — the queue's own status vocabulary, distinct from the training
               stage rail the console renders
* `failures` — is another attempt worth making, and what to record if not
* `queue`    — enqueue, claim, lease, finish, sweep
* `handlers` — what a handler is, and where cancellation is observed
* `worker`   — the claim loop the worker processes run

This module deliberately re-exports **nothing**, unlike its neighbours. The ORM
model in `graphrec.db.models.jobs` needs the vocabulary in `states`, and
`queue` needs the ORM model; a package `__init__` that imported `queue` would
close that into a cycle and make `graphrec.db.models` unimportable. Import from
the submodule you want.
"""

from __future__ import annotations
