"""What a call is, before anyone has decided to make it synchronously or not.

Every route in this SDK is described by one of these, built by a module-level
function in `resources/`, and then handed to either `Transport` or
`AsyncTransport`. That is what keeps the sync and async surfaces from drifting:
the route, the validation, the body and the decoding are written once, and the
two facades differ only by `await`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class CallOptions:
    """Per-call overrides. Every method takes one."""

    #: Overrides the client's budget for this call only. **Seconds** — this is
    #: Python, and every other timeout a caller passes in this language is in
    #: seconds. The TypeScript SDK uses milliseconds for the same reason.
    timeout: float | None = None
    #: Your own trace id, sent as `X-Request-Id`.
    #:
    #: `graphrec/http/middleware.py` echoes a supplied value (truncated to 64
    #: characters) into every log line for the request and into the `reference`
    #: on any error, which is what makes a support conversation about one
    #: specific request possible.
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class Spec:
    method: Literal["GET", "POST"]
    path: str
    body: dict[str, Any] | None = None
    #: Whether re-sending this exact request is safe.
    #:
    #: True only when the payload carries the deduplicating identifier the route
    #: keys on — `event_id`, `sync_id`, `batch_id`, `request_id`. This is a
    #: property of the *call site*, not of the method: a POST is idempotent here
    #: and a hypothetical one without a key would not be.
    idempotent: bool = False
    options: CallOptions | None = field(default=None)
