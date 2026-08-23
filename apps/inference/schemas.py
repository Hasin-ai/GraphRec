"""The data plane's wire shapes — BACKEND_PLAN §12.11, verbatim where it says.

Five request bodies and four responses. The bounds are settings rather than
literals (`recommendation_max_top_n` and friends), because a `422` for `top_n:
150` is a policy decision and policy that is compiled into a field annotation
cannot be changed without a deploy. They are resolved at import time from the
process's settings, which is the one place a per-process bound is legitimate:
this process serves one tenant and its limits do not vary per request.

**`model_version` and `strategy` are required in every recommendation
response** (ER-F-05). `model_version` is nullable — a fallback answer had no
model — but the field is always present, because `null` is a statement and an
absent key is an omission a client would have to guess about.

**`session_id` goes in and never comes back.** It is hashed on arrival
(`RecommendationInput.session_hash`) and no response model here has a field it
could be echoed into.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from graphrec.common.config import get_settings

_settings = get_settings()

MAX_TOP_N = _settings.recommendation_max_top_n
MAX_RECENT_EVENTS = _settings.recommendation_max_recent_events
MAX_EXCLUSIONS = _settings.recommendation_max_exclusions


class _Body(BaseModel):
    # `extra="forbid"`, so a caller who sends `tenant_id` gets a `422` rather
    # than a silently ignored field they might believe had an effect.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RecentEventBody(_Body):
    """One thing the customer just did, applied without retraining.

    `occurred_at` is optional because a caller streaming a live session has the
    order and not always the clock. Ordering is by position in the list, which
    is what the caller controls and what the funnel reads.
    """

    external_product_id: str = Field(min_length=1, max_length=200)
    event_type: str | None = Field(default=None, max_length=40)
    occurred_at: dt.datetime | None = None


class RecommendationRequestBody(_Body):
    """`POST /v1/recommendations`.

    One of `customer_id` or `session_id` is required, and the check is in the
    domain rather than in a validator here: the same rule governs
    `/recommendations/session`, and a `model_validator` on each body would be
    two statements of one requirement.
    """

    request_id: str = Field(min_length=1, max_length=200)
    customer_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    top_n: int = Field(default=10, ge=1, le=MAX_TOP_N)
    context: dict[str, str] = Field(default_factory=dict)
    recent_events: list[RecentEventBody] = Field(default_factory=list, max_length=MAX_RECENT_EVENTS)
    exclude_product_ids: list[str] = Field(default_factory=list, max_length=MAX_EXCLUSIONS)
    allow_fallback: bool = True


class SessionRecommendationRequestBody(_Body):
    """`POST /v1/recommendations/session` — XR-F-09, the anonymous path.

    A separate body rather than the same one with a comment, because
    `session_id` is *required* here. A shared body would make "session
    recommendations" a route that accepts a customer id, which is the one thing
    the endpoint exists not to need.
    """

    request_id: str = Field(min_length=1, max_length=200)
    session_id: str = Field(min_length=1, max_length=200)
    top_n: int = Field(default=10, ge=1, le=MAX_TOP_N)
    context: dict[str, str] = Field(default_factory=dict)
    recent_events: list[RecentEventBody] = Field(default_factory=list, max_length=MAX_RECENT_EVENTS)
    exclude_product_ids: list[str] = Field(default_factory=list, max_length=MAX_EXCLUSIONS)
    allow_fallback: bool = True


class ModelVersionBody(BaseModel):
    version_id: uuid.UUID
    version_number: int


class RecommendedItemBody(BaseModel):
    """One item, its rank, its score and where it came from.

    `candidate_source` is on every item rather than on the response, because a
    single response mixes lanes: the graph supplied eight and the category lane
    filled the last two, and a tenant tuning their surface needs to see which.
    """

    external_product_id: str
    rank: int
    score: float
    candidate_source: str


class RecommendationResponse(BaseModel):
    """The `200`. ER-F-05's two fields are `model_version` and `strategy`."""

    request_id: str
    model_version: ModelVersionBody | None
    strategy: str
    fallback_applied: bool
    items: list[RecommendedItemBody]
    ordering_policy_version: int
    latency_ms: int


class ImpressionBody(_Body):
    """One shown item. `position` is the rank the caller actually rendered,
    which need not be the rank returned — a page can drop an item."""

    event_id: str = Field(min_length=1, max_length=200)
    external_product_id: str = Field(min_length=1, max_length=200)
    position: int = Field(ge=1, le=MAX_TOP_N)


class ImpressionsRequestBody(_Body):
    """`POST /v1/feedback/impressions` — the `/integration` page's shape."""

    request_id: str = Field(min_length=1, max_length=200)
    impressions: list[ImpressionBody] = Field(min_length=1, max_length=MAX_TOP_N)


class FeedbackItemBody(_Body):
    """One click or conversion. `value` is meaningful on conversions only and
    is ignored on clicks rather than refused — a caller sending an order total
    on a click has sent something harmless, not something invalid."""

    event_id: str = Field(min_length=1, max_length=200)
    external_product_id: str = Field(min_length=1, max_length=200)
    value: float | None = Field(default=None, ge=0)


class FeedbackRequestBody(_Body):
    """`POST /v1/feedback/clicks` and `…/conversions`."""

    request_id: str = Field(min_length=1, max_length=200)
    events: list[FeedbackItemBody] = Field(min_length=1, max_length=MAX_TOP_N)


class FeedbackResponse(BaseModel):
    """`duplicate_confirmed` counted, not hidden.

    A retried batch is the normal consequence of a timeout on the caller's side.
    Reporting duplicates separately is what lets a client tell "you accepted my
    twenty again" from "you counted my twenty twice".
    """

    request_id: str
    received: int
    accepted: int
    duplicates: int
    unknown_products: list[str]


class HealthResponse(BaseModel):
    """`/healthz` — the process is up. Says nothing about the model."""

    status: str


class ReadyResponse(BaseModel):
    """`/readyz` — the process can answer with a model.

    This is what the driver reads to decide `serving_replicas.ready`, and
    therefore what the reconciler reads before swapping `active_version_id`.
    `detail` carries why not, so a failed activation is diagnosable from the
    replica rather than only from the reconciler's log.
    """

    ready: bool
    tenant_id: uuid.UUID
    model_version: ModelVersionBody | None
    epoch: int | None
    detail: str | None


__all__ = [
    "MAX_EXCLUSIONS",
    "MAX_RECENT_EVENTS",
    "MAX_TOP_N",
    "FeedbackItemBody",
    "FeedbackRequestBody",
    "FeedbackResponse",
    "HealthResponse",
    "ImpressionBody",
    "ImpressionsRequestBody",
    "ModelVersionBody",
    "ReadyResponse",
    "RecentEventBody",
    "RecommendationRequestBody",
    "RecommendationResponse",
    "RecommendedItemBody",
    "SessionRecommendationRequestBody",
]
