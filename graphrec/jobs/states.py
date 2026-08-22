"""The queue's own vocabulary.

Deliberately *not* in `graphrec/common/enums.py`. That module is generated from
the console prototype by `scripts/gen_enums.py`, and the `JobState` it defines —
`queued`, `waiting_for_resources`, `preparing_data`, … , `registering` — is the
**training job's** stage rail (dc.html L623). It describes what a training run is
doing. This module describes whether a queued unit of work has been picked up,
which is a different question about a different thing, asked of every job type
including ones that never train anything.

Conflating them would mean an event-batch job reporting `indexing_embeddings`.
"""

from __future__ import annotations

from enum import StrEnum


class QueueStatus(StrEnum):
    """Where a row sits in the queue. Five values, and the CHECK constraint in
    migration 0006 admits no others.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Terminal means finished: `completed_at` is set, no lease is held, and no
#: worker will touch the row again. The database enforces both halves.
TERMINAL_STATUSES = frozenset({QueueStatus.SUCCEEDED, QueueStatus.FAILED, QueueStatus.CANCELLED})

#: The two statuses the partial claim index covers.
LIVE_STATUSES = frozenset({QueueStatus.QUEUED, QueueStatus.RUNNING})


class JobType(StrEnum):
    """What a job does, which decides which handler runs it.

    A worker process subscribes to a subset — training is separated onto
    `training_worker` because a GPU-shaped process should not be occupied
    validating a CSV, and because training is globally serialised (ASM-03)
    while ingestion is not.
    """

    EVENT_BATCH = "event_batch"
    PRODUCT_BULK_UPSERT = "product_bulk_upsert"
    TRAINING = "training"
    USAGE_ROLLUP = "usage_rollup"


#: Which process claims what. `job_worker` takes the ingestion types;
#: `training_worker` takes training alone.
INGESTION_JOB_TYPES = (JobType.EVENT_BATCH, JobType.PRODUCT_BULK_UPSERT, JobType.USAGE_ROLLUP)
TRAINING_JOB_TYPES = (JobType.TRAINING,)


__all__ = [
    "INGESTION_JOB_TYPES",
    "LIVE_STATUSES",
    "TERMINAL_STATUSES",
    "TRAINING_JOB_TYPES",
    "JobType",
    "QueueStatus",
]
