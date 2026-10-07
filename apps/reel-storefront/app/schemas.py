"""Browser-facing models. camelCase on the wire; inputs reject unknown fields."""

from __future__ import annotations

from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

T = TypeVar("T")
Shelf = Literal["home", "more_like"]


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True)


class Input(Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True, extra="forbid")


class Envelope(Wire, Generic[T]):
    data: T
    meta: Dict[str, Any] = Field(default_factory=dict)


class Film(Wire):
    id: str
    title: str
    year: Optional[int]
    genres: List[str]
    #: Community tags from MovieLens tags.csv, most-used first (see scripts/film_tags.py).
    tags: List[str] = []
    popularity: int
    popularity_rank: int
    tmdb_id: Optional[str] = None
    imdb_id: Optional[str] = None
    poster_url: Optional[str] = None


class FilmPage(Wire):
    items: List[Film]
    total: int
    offset: int
    limit: int


class Genre(Wire):
    name: str
    films: int


class Tag(Wire):
    name: str
    films: int


class PersonaOut(Wire):
    key: str
    name: str
    blurb: str
    color: str
    user_id: Optional[str]
    history_length: int


class SessionOut(Wire):
    persona: PersonaOut
    session_id: str
    personas: List[PersonaOut]


class PersonaIn(Input):
    persona: str = Field(min_length=1, max_length=32)
    #: Re-record this anonymous session's watched films under the persona (Act 2 hand-off).
    carry_session: bool = False


class WatchIn(Input):
    film_id: str = Field(min_length=1, max_length=20)
    #: Set when the watch came from a recommendation shelf: also sends conversion feedback.
    request_id: Optional[str] = Field(default=None, max_length=200)
    position: Optional[int] = Field(default=None, ge=1, le=100)


class Receipt(Wire):
    event_id: str
    event_type: str
    film_id: str
    accepted: bool
    duplicate: bool
    latency_ms: int
    feedback: Optional[str] = None


class RecommendationIn(Input):
    shelf: Shelf = "home"
    #: For ``more_like``: the film the shelf is about.
    film_id: Optional[str] = Field(default=None, max_length=20)


class Ranked(Film):
    position: int
    change: Literal["new", "up", "down", "same"] = "same"
    previous_position: Optional[int] = None


class TraceRequest(Wire):
    endpoint: str
    user_id: Optional[str]
    top_n: int
    recent_product_ids: List[str]
    exclude_count: int


class Trace(Wire):
    request: TraceRequest
    request_id: str
    model_version_id: Optional[str]
    strategy: str
    fallback_used: bool
    fallback_tier: str
    applied_rules: List[str]
    latency_ms: int


class Diff(Wire):
    has_previous: bool
    entered: List[str]
    left: List[Film]
    changed: int
    summary: str


class RecommendationsOut(Wire):
    shelf: Shelf
    title: str
    items: List[Ranked]
    trace: Trace
    diff: Diff
    omitted: int
    impression: Optional[str] = None


class Unavailable(Wire):
    available: Literal[False] = False
    reason: str
    correlation_id: Optional[str] = None


class ClickIn(Input):
    request_id: str = Field(min_length=1, max_length=200)
    film_id: str = Field(min_length=1, max_length=20)
    position: int = Field(ge=1, le=100)


class FeedbackOut(Wire):
    event_id: str
    accepted: bool
    duplicate: bool


class SequenceItem(Wire):
    film: Film
    time: int
    origin: Literal["training", "live"]
    event_type: str
    event_id: Optional[str] = None
    in_window: bool
    evicted: bool = False


class SequenceOut(Wire):
    shopper: str
    total: int
    window: int
    items: List[SequenceItem]
    live_count: int
    session_only: bool


class StatusOut(Wire):
    tenant: str
    graphrec: str
    model_version_id: Optional[str]
    model_version_tag: Optional[str]
    model_card: Dict[str, Any]
    live_events: int
