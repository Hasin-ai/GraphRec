"""What `job_worker` can run.

Empty at the end of Phase 4, and that is not an oversight. The claim loop, the
lease and the retry policy are this phase's deliverables; the work they carry —
event batches and bulk product upserts — arrives in Phase 6, and the training
handler in Phase 8 on `training_worker`.

The registry is what the worker derives its claim filter from, so an empty one
means the process claims nothing and says so at startup rather than leasing
jobs it cannot run and spending tenants' attempts on the deployment's mistake.
"""

from __future__ import annotations

from graphrec.jobs.handlers import HandlerRegistry

registry = HandlerRegistry()

# Phase 6 registers:
#   @registry.register(JobType.EVENT_BATCH)
#   @registry.register(JobType.PRODUCT_BULK_UPSERT)
# Phase 7 registers:
#   @registry.register(JobType.USAGE_ROLLUP)

__all__ = ["registry"]
