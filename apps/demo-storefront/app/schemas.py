"""Browser-facing models. Wire names are camelCase; inputs forbid unknown fields."""

from __future__ import annotations

from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

T = TypeVar("T")

ProofStatus = Literal["model_verified", "serving_preview", "catalog_fallback"]
BrowserAction = Literal["view", "add_to_cart", "remove_from_cart", "search", "add_to_wishlist"]
Surface = Literal["catalog", "product_detail", "cart", "order", "compare"]


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True)


class Input(Wire):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True, extra="forbid"
    )


class Envelope(Wire, Generic[T]):
    data: T
    meta: Dict[str, Any] = Field(default_factory=dict)


# -- session ----------------------------------------------------------------------------


class PersonaOut(Wire):
    key: str
    name: str
    blurb: str
    color: str
    user_id: Optional[str]


class SessionOut(Wire):
    persona: PersonaOut
    session_id: str
    personas: List[PersonaOut]


class PersonaIn(Input):
    persona: str = Field(min_length=1, max_length=32)


# -- catalog ----------------------------------------------------------------------------


class ProductOut(Wire):
    external_id: str
    title: str
    description: Optional[str]
    price: str
    category: str
    is_active: bool
    availability_status: str
    available: bool
    brand: Optional[str] = None
    size: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    accent: Optional[str] = None


# -- events -----------------------------------------------------------------------------


class EventIn(Input):
    action: BrowserAction
    product_id: Optional[str] = Field(default=None, max_length=100)
    quantity: int = Field(default=1, ge=1, le=99)
    price: Optional[str] = Field(default=None, max_length=32)
    query: Optional[str] = Field(default=None, max_length=200)
    surface: Surface = "catalog"

    @field_validator("product_id")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else value


class EventOut(Wire):
    event_id: str
    event_type: str
    queued: bool = True


# -- recommendations --------------------------------------------------------------------


class RecommendationIn(Input):
    top_n: int = Field(default=5, ge=1, le=20)
    exclude_product_ids: List[str] = Field(default_factory=list, max_length=50)
    recent_product_ids: List[str] = Field(default_factory=list, max_length=20)
    surface: Surface = "catalog"


class Provenance(Wire):
    request_id: str
    model_version_id: Optional[str]
    raw_strategy: str
    fallback_used: bool
    fallback_tier: str
    proof_status: ProofStatus
    excluded_count: int
    omitted_product_count: int
    impression_event_id: Optional[str] = None


class RecommendedProduct(ProductOut):
    position: int


class RecommendationsOut(Wire):
    items: List[RecommendedProduct]
    provenance: Provenance


class RecommendationsUnavailable(Wire):
    available: Literal[False] = False
    reason: str
    correlation_id: Optional[str] = None


class ClickIn(Input):
    request_id: str = Field(min_length=1, max_length=200)
    product_id: str = Field(min_length=1, max_length=100)
    position: int = Field(ge=1, le=100)
    surface: Surface = "catalog"


class FeedbackOut(Wire):
    event_id: str
    accepted: bool
    duplicate: bool


# -- purchase ---------------------------------------------------------------------------


class PurchaseLineIn(Input):
    product_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=99)


class PurchaseIn(Input):
    lines: List[PurchaseLineIn] = Field(min_length=1, max_length=20)
    #: Browser-generated, so a retried request produces the same order id and events.
    client_order_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    surface: Surface = "cart"


class PurchaseLineOut(Wire):
    product_id: str
    title: str
    quantity: int
    unit_price: str
    line_total: str
    event_id: str


class PurchaseOut(Wire):
    order_id: str
    lines: List[PurchaseLineOut]
    total: str
    accepted_count: int
    duplicate_count: int
    rejected_count: int


# -- compare ----------------------------------------------------------------------------


class CompareItem(Wire):
    position: int
    external_id: str
    title: str
    category: str
    price: str
    accent: Optional[str] = None
    #: Present in every persona's list.
    shared: bool = False


class CompareColumn(Wire):
    persona: PersonaOut
    items: List[CompareItem]
    provenance: Optional[Provenance]
    repeatable: Optional[bool]
    error: Optional[str] = None


class PairSimilarity(Wire):
    a: str
    b: str
    overlap: int
    jaccard: float


class CompareSummary(Wire):
    top_n: int
    excluded_product_ids: List[str]
    unique_products: int
    slots: int
    distinct_orderings: int
    known_personas_identical: bool
    all_repeatable: Optional[bool]
    any_model_version: bool
    gate_passed: bool
    gate_reason: str


class CompareOut(Wire):
    columns: List[CompareColumn]
    pairs: List[PairSimilarity]
    summary: CompareSummary


# -- health -----------------------------------------------------------------------------


class HealthOut(Wire):
    storefront: Literal["ok"] = "ok"
    graphrec: str
    graphrec_base_url: str
    proof_configured: bool
    proof_version_id: Optional[str]
    catalog_products: Optional[int] = None
    correlation_id: Optional[str] = None
