"""Reading a submission, and the loop every integration otherwise writes itself.

Bulk upsert and event batches answer `202` with a submission that is
`processing`: the work happens in the job worker and the counts arrive later. So
every customer writes a poll, and the interesting part is that most of them
write the same three bugs — a fixed interval that hammers the API, no ceiling so
a stuck job spins forever, and treating `failed` as an exception without keeping
the per-item `errors` that say what to fix. `wait` is here so that loop is
written once.

A submission is addressable by its id or by the identifier you chose, and by
nothing else — there is no submission index
(`apps/control_api/routers/ingestion.py`), which is why these classes have no
`list`.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import quote

import anyio

from .._spec import CallOptions, Spec
from .._validate import parse
from ..errors import GraphRecError
from ..models import Submission

if TYPE_CHECKING:
    from ..transport import AsyncTransport, Transport

#: Poll cadence: gentle at first because most submissions finish quickly.
FIRST_POLL = 0.5
POLL_FACTOR = 1.5
MAX_POLL = 5.0
DEFAULT_WAIT = 60.0


def decode_submission(payload: object) -> Submission:
    return parse(Submission, payload)


def get_spec(submission_id: str, options: CallOptions | None = None) -> Spec:
    return Spec(
        "GET", f"/v1/submissions/{quote(submission_id, safe='')}", idempotent=True, options=options
    )


def get_batch_spec(batch_id: str, options: CallOptions | None = None) -> Spec:
    return Spec(
        "GET", f"/v1/events/batches/{quote(batch_id, safe='')}", idempotent=True, options=options
    )


class SubmissionTimeoutError(GraphRecError):
    """`wait` gave up before the submission reached a terminal state.

    Carries the last state it saw, so the caller can keep polling with their own
    scheduler instead of starting over. A bare timeout would throw away the one
    thing that makes resuming possible.
    """

    def __init__(self, submission: Submission, waited: float) -> None:
        super().__init__(
            f"Submission {submission.submission_id} was still {submission.stage} after "
            f"{waited}s. It has not failed — poll it again with `submissions.get`.",
            code="submission_not_ready",
            error_class="unavailable",
            reason="The submission has not finished yet.",
            reference=None,
            retryable=True,
        )
        self.submission = submission


class SubmissionFailedError(GraphRecError):
    """The submission finished and its verdict is `failed`.

    Raised by `wait` only. `get` returns a failed submission as a value, because
    asking how a batch went and being told "badly" is a successful call.
    """

    def __init__(self, submission: Submission) -> None:
        from ..errors import FieldError

        code = submission.failure_code or "submission_failed"
        super().__init__(
            f"Submission {submission.submission_id} failed"
            + (f" ({submission.failure_code})" if submission.failure_code else "")
            + f": {submission.counts.failed} of {submission.counts.received} item(s) "
            "were rejected.",
            code=code,
            error_class="validation",
            reason="The submission failed.",
            reference=submission.reference,
            field_errors=[FieldError(item.ref, item.reason) for item in submission.errors],
        )
        self.submission = submission


def _poll_options(options: CallOptions | None, remaining: float) -> CallOptions:
    # Each poll gets what remains, so the wait is one budget rather than a
    # budget per request multiplied by an unbounded number of requests.
    return CallOptions(
        timeout=max(remaining, 0.001),
        request_id=options.request_id if options else None,
    )


class Submissions:
    """Submissions, blocking."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def get(self, submission_id: str, *, options: CallOptions | None = None) -> Submission:
        """By submission id, as returned from `catalog.sync` or `events.submit_batch`."""
        return decode_submission(self._transport.send(get_spec(submission_id, options)))

    def get_batch(self, batch_id: str, *, options: CallOptions | None = None) -> Submission:
        """By the `batch_id` you chose.

        The reason this exists: if the `202` never reached you, you do not have a
        submission id — but you do have the identifier you sent, and that is
        enough to find out whether the batch landed. Without it, a timeout on
        submit leaves an integration with no way to ask.
        """
        return decode_submission(self._transport.send(get_batch_spec(batch_id, options)))

    def wait(
        self,
        submission_id: str,
        *,
        timeout: float = DEFAULT_WAIT,
        options: CallOptions | None = None,
    ) -> Submission:
        """Poll until the submission is terminal.

        Returns on `succeeded`, raises `SubmissionFailedError` on `failed` with
        the per-item reasons attached, and raises `SubmissionTimeoutError`
        carrying the last state when the budget runs out.
        """
        deadline = time.monotonic() + timeout
        interval = FIRST_POLL
        while True:
            latest = self.get(
                submission_id, options=_poll_options(options, deadline - time.monotonic())
            )
            if latest.status == "succeeded":
                return latest
            if latest.status == "failed":
                raise SubmissionFailedError(latest)

            pause = min(interval, deadline - time.monotonic())
            if pause <= 0:
                raise SubmissionTimeoutError(latest, timeout)
            time.sleep(pause)
            interval = min(interval * POLL_FACTOR, MAX_POLL)


class AsyncSubmissions:
    """Submissions, awaited."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def get(self, submission_id: str, *, options: CallOptions | None = None) -> Submission:
        """By submission id, as returned from `catalog.sync` or `events.submit_batch`."""
        return decode_submission(await self._transport.send(get_spec(submission_id, options)))

    async def get_batch(self, batch_id: str, *, options: CallOptions | None = None) -> Submission:
        """By the `batch_id` you chose.

        The reason this exists: if the `202` never reached you, you do not have a
        submission id — but you do have the identifier you sent, and that is
        enough to find out whether the batch landed. Without it, a timeout on
        submit leaves an integration with no way to ask.
        """
        return decode_submission(await self._transport.send(get_batch_spec(batch_id, options)))

    async def wait(
        self,
        submission_id: str,
        *,
        timeout: float = DEFAULT_WAIT,
        options: CallOptions | None = None,
    ) -> Submission:
        """Poll until the submission is terminal.

        Returns on `succeeded`, raises `SubmissionFailedError` on `failed` with
        the per-item reasons attached, and raises `SubmissionTimeoutError`
        carrying the last state when the budget runs out.
        """
        deadline = time.monotonic() + timeout
        interval = FIRST_POLL
        while True:
            latest = await self.get(
                submission_id, options=_poll_options(options, deadline - time.monotonic())
            )
            if latest.status == "succeeded":
                return latest
            if latest.status == "failed":
                raise SubmissionFailedError(latest)

            pause = min(interval, deadline - time.monotonic())
            if pause <= 0:
                raise SubmissionTimeoutError(latest, timeout)
            await anyio.sleep(pause)
            interval = min(interval * POLL_FACTOR, MAX_POLL)
