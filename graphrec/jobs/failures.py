"""How a job ends badly, and what the queue should do about it.

The classifier's job is to answer one question — *is trying again likely to
produce a different result?* — and it answers it from information that already
exists rather than from a new vocabulary invented for workers.

`GraphRecError` has carried a `retryable` flag since Phase 1, because the API
already had to tell a client whether to retry. A worker asks the same question
of the same exception, so it reads the same flag. A parallel taxonomy would
drift the moment somebody set one and forgot the other.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.exc import DBAPIError, OperationalError

from graphrec.common.errors import GraphRecError


class Retryability(StrEnum):
    RETRYABLE = "retryable"
    PERMANENT = "permanent"


class JobCancelled(Exception):  # noqa: N818 - control flow, not a failure
    """Raised by a handler when it observes a cancellation request.

    Cancellation is cooperative: the handler raises this at a stage boundary,
    where it knows what it has finished and what it has not. Nothing interrupts
    a handler mid-statement, because a job stopped between two writes is a job
    whose partial effects nobody has described.
    """

    def __init__(self, stage: str | None = None) -> None:
        self.stage = stage
        super().__init__(stage or "cancelled")


class PermanentJobError(Exception):
    """A handler's way of saying "this will fail identically forever".

    A malformed CSV, a payload naming a product that does not exist, a dataset
    below the training minimum. Retrying spends the tenant's attempts to reach
    the same answer more slowly.
    """

    def __init__(self, code: str, **copy_args: object) -> None:
        self.code = code
        self.copy_args = copy_args
        super().__init__(code)


#: Exception types that mean "the infrastructure was unwell", not "the work was
#: wrong". A dropped connection says nothing about the payload.
_RETRYABLE_TYPES: tuple[type[BaseException], ...] = (
    OperationalError,
    DBAPIError,
    asyncio.TimeoutError,
    TimeoutError,
    ConnectionError,
    OSError,
)


@dataclass(frozen=True, slots=True)
class Verdict:
    """The classifier's answer: what to do, and what to record if we stop."""

    retryability: Retryability
    code: str
    copy_args: dict[str, object]

    @property
    def should_retry(self) -> bool:
        return self.retryability is Retryability.RETRYABLE


def classify(exc: BaseException) -> Verdict:
    """Decide whether `exc` is worth another attempt.

    The order matters. A `PermanentJobError` is the handler's explicit
    verdict and outranks everything. A `GraphRecError` carries its own flag.
    Only an exception that has said nothing about itself falls through to the
    type table.
    """
    if isinstance(exc, PermanentJobError):
        return Verdict(Retryability.PERMANENT, exc.code, dict(exc.copy_args))

    if isinstance(exc, GraphRecError):
        return Verdict(
            Retryability.RETRYABLE if exc.retryable else Retryability.PERMANENT,
            exc.code,
            dict(exc.copy_args),
        )

    if isinstance(exc, _RETRYABLE_TYPES):
        return Verdict(Retryability.RETRYABLE, "job_failed", {})

    # An unrecognised exception is treated as retryable, which is the less
    # damaging of two wrong answers. Retrying a genuinely deterministic bug
    # wastes at most `max_attempts` runs and then stops; refusing to retry a
    # transient one silently drops a tenant's ingestion. The attempt cap is what
    # makes the optimistic default safe.
    return Verdict(Retryability.RETRYABLE, "job_failed", {})


#: Backoff doubles per consumed attempt from `BACKOFF_BASE_SECONDS`, capped.
#: Small, because these are minutes-long batch jobs on a queue measured in tens
#: of jobs per day (ASM-03), not a thundering herd of retries.
BACKOFF_BASE_SECONDS = 5
BACKOFF_CAP_SECONDS = 300


def backoff_seconds(attempt: int) -> int:
    """Seconds to wait before a job that has consumed `attempt` attempts reruns."""
    if attempt <= 0:
        return BACKOFF_BASE_SECONDS
    return int(min(BACKOFF_BASE_SECONDS * 2**attempt, BACKOFF_CAP_SECONDS))


__all__ = [
    "BACKOFF_CAP_SECONDS",
    "JobCancelled",
    "PermanentJobError",
    "Retryability",
    "Verdict",
    "backoff_seconds",
    "classify",
]
