"""What `job_worker` can run.

Two handlers, both deferred halves of an ingestion route: the request accepted
the collection and returned `202` with a submission, and these apply it.

The registry is what the worker derives its claim filter from, so a type absent
here is a type this process never leases. That is deliberate rather than
incidental — training is registered on `training_worker` instead, because a
process that could claim a four-hour training job would starve the ingestion
queue behind it.
"""

from __future__ import annotations

from graphrec.domain.ingestion.processor import process_event_batch, process_product_bulk_upsert
from graphrec.jobs.handlers import HandlerRegistry
from graphrec.jobs.states import JobType

registry = HandlerRegistry()

registry.register(JobType.EVENT_BATCH)(process_event_batch)
registry.register(JobType.PRODUCT_BULK_UPSERT)(process_product_bulk_upsert)

# Phase 7 registers:
#   @registry.register(JobType.USAGE_ROLLUP)

__all__ = ["registry"]
