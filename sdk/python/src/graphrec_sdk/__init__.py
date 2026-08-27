"""Call the GraphRec API from your own service.

Server-side only. Every call carries a `gr_live_` credential, which is a bearer
token with tenant-wide scope; shipped to a browser it is in the bundle, in the
devtools network tab and in the extension that reads both. See `README.md` for
the full reasoning and the shape that works instead.

    from graphrec_sdk import GraphRec

    gr = GraphRec(api_key=..., tenant_id=..., domain="graphrec.example")
    answer = gr.recommendations.for_customer(request_id=..., customer_id="c-1", top_n=10)
"""

from __future__ import annotations

from ._spec import CallOptions
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
from .client import AsyncGraphRec, GraphRec
from .config import VERSION, normalise_tenant_id
from .credential import Credential
from .errors import (
    APITimeoutError,
    AuthenticationError,
    ConfigurationError,
    ConflictError,
    ErrorClass,
    FieldError,
    GraphRecError,
    InternalError,
    LimitError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExhaustedError,
    RateLimitedError,
    TransportError,
    UnavailableError,
    ValidationError,
)
from .models import (
    Availability,
    CatalogSync,
    CustomerRecommendationRequest,
    EventBatch,
    EventInput,
    EventReceipt,
    EventType,
    FeedbackEvent,
    FeedbackRequest,
    FeedbackResponse,
    ModelVersion,
    ProductInput,
    RecentEvent,
    RecommendationResponse,
    RecommendedItem,
    SessionRecommendationRequest,
    Submission,
    SubmissionCounts,
    SubmissionErrorItem,
    SubmissionKind,
    SubmissionOutcome,
    SubmissionStage,
    SyncMode,
)
from .resources import SubmissionFailedError, SubmissionTimeoutError

__version__ = VERSION

__all__ = [
    "MAX_CATEGORY",
    "MAX_DATA_PLANE_ID",
    "MAX_DESCRIPTION",
    "MAX_EVENTS_PER_BATCH",
    "MAX_EXCLUSIONS",
    "MAX_EXTERNAL_ID",
    "MAX_FEEDBACK_EVENTS",
    "MAX_PRODUCTS_PER_SYNC",
    "MAX_RECENT_EVENTS",
    "MAX_TITLE",
    "MAX_TOP_N",
    "VERSION",
    "APITimeoutError",
    "AsyncGraphRec",
    "AuthenticationError",
    "Availability",
    "CallOptions",
    "CatalogSync",
    "ConfigurationError",
    "ConflictError",
    "Credential",
    "CustomerRecommendationRequest",
    "ErrorClass",
    "EventBatch",
    "EventInput",
    "EventReceipt",
    "EventType",
    "FeedbackEvent",
    "FeedbackRequest",
    "FeedbackResponse",
    "FieldError",
    "GraphRec",
    "GraphRecError",
    "InternalError",
    "LimitError",
    "ModelVersion",
    "NotFoundError",
    "PermissionDeniedError",
    "ProductInput",
    "QuotaExhaustedError",
    "RateLimitedError",
    "RecentEvent",
    "RecommendationResponse",
    "RecommendedItem",
    "SessionRecommendationRequest",
    "Submission",
    "SubmissionCounts",
    "SubmissionErrorItem",
    "SubmissionFailedError",
    "SubmissionKind",
    "SubmissionOutcome",
    "SubmissionStage",
    "SubmissionTimeoutError",
    "SyncMode",
    "TransportError",
    "UnavailableError",
    "ValidationError",
    "normalise_tenant_id",
]
