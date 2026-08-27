"""The typed surface: Pydantic v2 models for what goes out and what comes back.

`snake_case` on the wire and `snake_case` in Python, so unlike the TypeScript
SDK there is no renaming layer here and none is invented — a field is called
what the API calls it, and the OpenAPI document is directly readable as
documentation for this package.

**Requests forbid unknown fields; responses ignore them.** The asymmetry is
deliberate. A typo in a request (`extenal_id=`) is silently dropped by a
permissive model and shows up as a rejected item inside a submission much later,
so requests are strict. A *response* that grew a field is the API being extended
compatibly, and a strict response model would turn that into an outage in every
deployed copy of this SDK, so responses are lenient.

**Bounds are on the models.** `top_n` ≤ 100, `recent_events` ≤ 50,
`exclude_product_ids` ≤ 200, `external_id` ≤ 120 characters. Pydantic raises its
own `ValidationError`; `_errors.to_graphrec` converts it into this package's, so
a caller writes one `except graphrec_sdk.ValidationError` for a rejection whether
it happened at their desk or at the server.

**`value` differs by plane on purpose.** `EventInput.value` is a decimal string
because it is money a tenant may be billed against and a float cannot hold
"129.00" exactly. `FeedbackEvent.value` is a float because it is a signal into a
ranking model. Papering over the difference would silently change one of them.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer

from .bounds import (
    MAX_CATEGORY,
    MAX_DATA_PLANE_ID,
    MAX_DESCRIPTION,
    MAX_EVENTS_PER_BATCH,
    MAX_EXCLUSIONS,
    MAX_EXTERNAL_ID,
    MAX_FEEDBACK_EVENTS,
    MAX_PRODUCTS_PER_SYNC,
    MAX_RECENT_EVENTS,
    MAX_TITLE,
    MAX_TOP_N,
)

EventType = Literal["view", "add_to_cart", "purchase", "remove_from_cart"]
Availability = Literal["in_stock", "low_stock", "out_of_stock"]
SyncMode = Literal["upsert", "upsert_and_disable_missing"]
SubmissionKind = Literal["product_sync", "event_batch"]
#: The terminal-facing verdict. `processing` until the worker has finished.
SubmissionOutcome = Literal["processing", "succeeded", "failed"]
#: Where in the pipeline it is. Ordered; the console draws a rail from it.
SubmissionStage = Literal["received", "validating", "applying", "completed", "failed"]

DataPlaneId = Annotated[str, Field(min_length=1, max_length=MAX_DATA_PLANE_ID)]
ExternalId = Annotated[str, Field(min_length=1, max_length=MAX_EXTERNAL_ID)]

#: An RFC 3339 instant that carries an offset.
#:
#: `parse_timestamp` refuses a naive timestamp rather than assuming UTC:
#: "2026-08-14 09:41" is a different instant in different places and guessing
#: would silently reorder a tenant's event history. `AwareDatetime` refuses the
#: same value for the same reason, at the caller's desk instead of per item.
Instant = AwareDatetime


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------- data plane


class RecentEvent(_Request):
    """One interaction to condition this request on. Not persisted as an event."""

    external_product_id: DataPlaneId
    event_type: EventType | None = None
    occurred_at: Instant | None = None

    @field_serializer("occurred_at")
    def _serialise_occurred_at(self, value: datetime | None) -> str | None:
        return value.isoformat() if value else None


class _RecommendationRequest(_Request):
    #: Yours to choose, and the idempotency key for this call (`Ultimate` §27).
    #:
    #: It is also what ties a later impression, click or conversion back to the
    #: answer that produced them, so keep it for as long as you keep the page.
    request_id: DataPlaneId
    top_n: Annotated[int, Field(ge=1, le=MAX_TOP_N)] | None = None
    recent_events: Annotated[list[RecentEvent], Field(max_length=MAX_RECENT_EVENTS)] | None = None
    exclude_product_ids: Annotated[list[DataPlaneId], Field(max_length=MAX_EXCLUSIONS)] | None = (
        None
    )
    context: dict[str, Any] | None = None
    #: When `False`, a request that finds no ready model is refused
    #: ``503 model_not_ready`` instead of being served a popularity list.
    #:
    #: A product decision, not a transport one: it asks whether a generic answer
    #: is worse than no answer on this surface. The SDK never sets it for you
    #: and never retries past it.
    allow_fallback: bool | None = None


class CustomerRecommendationRequest(_RecommendationRequest):
    customer_id: DataPlaneId
    session_id: DataPlaneId | None = None


class SessionRecommendationRequest(_RecommendationRequest):
    session_id: DataPlaneId


class ModelVersion(_Response):
    version_id: str
    version_number: int


class RecommendedItem(_Response):
    external_product_id: str
    rank: int
    score: float
    #: Which generator proposed it — useful when reading a fallback answer.
    candidate_source: str


class RecommendationResponse(_Response):
    request_id: str
    #: `None` when `fallback_applied` is true: no model served this.
    model_version: ModelVersion | None = None
    strategy: str
    fallback_applied: bool
    items: list[RecommendedItem]
    ordering_policy_version: int
    latency_ms: int

    # `model_` is Pydantic's own namespace and `model_version` is the API's
    # field name. Renaming it here would put a second spelling of one field into
    # customers' code; clearing the protected namespace is the smaller cost.
    model_config = ConfigDict(extra="ignore", protected_namespaces=())


class FeedbackEvent(_Request):
    #: Yours, and the per-item idempotency key. An order line, a click id.
    event_id: DataPlaneId
    external_product_id: DataPlaneId
    #: A float here, unlike an ingestion event's `value`, which is a string.
    #: See the module docstring.
    value: float | None = None


class FeedbackRequest(_Request):
    #: The `request_id` of the recommendation these events are about.
    request_id: DataPlaneId
    events: Annotated[list[FeedbackEvent], Field(min_length=1, max_length=MAX_FEEDBACK_EVENTS)]


class FeedbackResponse(_Response):
    request_id: str
    received: int
    accepted: int
    #: Events already reported under this `request_id`. A retry lands here.
    duplicates: int
    #: Identifiers not in your catalogue. Not an error; worth a metric.
    unknown_products: list[str]


# ------------------------------------------------------------- control plane


class EventInput(_Request):
    """One interaction, for the ingestion plane."""

    #: The idempotency key. Resending confirms the first rather than counting twice.
    event_id: ExternalId
    customer_id: ExternalId
    external_product_id: ExternalId
    event_type: EventType
    occurred_at: Instant
    #: A decimal *string* — "129.00". See the module docstring.
    value: Decimal | str | None = None
    context: dict[str, Any] | None = None

    @field_serializer("occurred_at")
    def _serialise_occurred_at(self, value: datetime) -> str:
        return value.isoformat()

    @field_serializer("value")
    def _serialise_value(self, value: Decimal | str | None) -> str | None:
        return None if value is None else str(value)


class EventBatch(_Request):
    #: The collection's idempotency key. A repeat returns the original submission.
    batch_id: ExternalId
    events: Annotated[list[EventInput], Field(min_length=1, max_length=MAX_EVENTS_PER_BATCH)]


class EventReceipt(_Response):
    event_id: str
    status: Literal["accepted", "duplicate_confirmed"]
    #: Set only on `duplicate_confirmed`: when the first copy arrived.
    first_received_at: datetime | None = None


class ProductInput(_Request):
    external_id: ExternalId
    title: Annotated[str, Field(min_length=1, max_length=MAX_TITLE)]
    description: Annotated[str, Field(max_length=MAX_DESCRIPTION)] | None = None
    category: Annotated[str, Field(max_length=MAX_CATEGORY)] | None = None
    brand: Annotated[str, Field(max_length=MAX_CATEGORY)] | None = None
    #: A decimal string or a number; sent as given. Money, so a string is safer.
    price: Decimal | str | float | None = None
    #: Defaults to `in_stock` server-side — a sync states the catalogue's contents.
    availability: Availability | None = None
    #: Defaults to `True` server-side.
    active: bool | None = None
    attributes: dict[str, Any] | None = None

    @field_serializer("price")
    def _serialise_price(self, value: Decimal | str | float | None) -> str | float | None:
        return str(value) if isinstance(value, Decimal) else value


class CatalogSync(_Request):
    #: The collection's idempotency key.
    sync_id: ExternalId
    products: Annotated[list[ProductInput], Field(min_length=1, max_length=MAX_PRODUCTS_PER_SYNC)]
    #: `upsert_and_disable_missing` treats the payload as the whole catalogue
    #: and disables anything absent from it. On a partial sync that empties a shop.
    mode: SyncMode | None = None


class SubmissionCounts(_Response):
    #: `received == accepted + updated + skipped + failed`, always.
    received: int
    accepted: int
    updated: int
    #: Labelled "Duplicates" for an event batch and "Skipped" for a sync.
    skipped: int
    failed: int


class SubmissionErrorItem(_Response):
    #: An identifier you sent, truncated. Never your payload echoed back.
    ref: str
    reason: str


class Submission(_Response):
    submission_id: str
    kind: SubmissionKind
    status: SubmissionOutcome
    stage: SubmissionStage
    #: The `sync_id` or `batch_id` you chose.
    reference: str
    counts: SubmissionCounts
    errors: list[SubmissionErrorItem] = Field(default_factory=list)
    error_count: int = 0
    failure_code: str | None = None
    submitted_at: datetime
    completed_at: datetime | None = None
