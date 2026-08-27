"""The five namespaces, each bound to exactly one plane.

Every module here is the same three parts. A module-level function per route
builds the `Spec` — validating the arguments, encoding the body, naming the path
and declaring whether a retry is safe. A module-level function decodes the
reply. Then two facade classes, sync and async, whose methods are one line each.

The duplication between the facades is signatures, never logic, and it is
deliberate: the alternative — one class whose methods return something awaitable
in one mode and not in the other — is untypeable and unreadable at the call
site. `tests/sdk/test_surface.py` asserts the two facades expose the same method
names with the same signatures, so the duplication cannot drift.
"""

from __future__ import annotations

from .catalog import AsyncCatalog, Catalog
from .events import AsyncEvents, Events
from .feedback import AsyncFeedback, Feedback
from .recommendations import AsyncRecommendations, Recommendations
from .submissions import (
    AsyncSubmissions,
    SubmissionFailedError,
    Submissions,
    SubmissionTimeoutError,
)

__all__ = [
    "AsyncCatalog",
    "AsyncEvents",
    "AsyncFeedback",
    "AsyncRecommendations",
    "AsyncSubmissions",
    "Catalog",
    "Events",
    "Feedback",
    "Recommendations",
    "SubmissionFailedError",
    "SubmissionTimeoutError",
    "Submissions",
]
