"""Event construction shared by the sync and async trackers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Union

from .._ids import deterministic_id
from .._validation import coerce_input
from ..enums import EventType
from ..errors import InputValidationError
from ..models.events import EventInput

Number = Union[Decimal, float, int, str]


class EventBuilder:
    """Typed constructors for common e-commerce interactions."""

    def __init__(self, *, default_context: Optional[Mapping[str, Any]] = None) -> None:
        self.default_context: Dict[str, Any] = dict(default_context or {})

    def build(
        self,
        event_type: Union[EventType, str],
        *,
        user_id: Optional[str] = None,
        product_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        occurred_at: Optional[datetime] = None,
        event_id: Optional[str] = None,
    ) -> EventInput:
        merged: Dict[str, Any] = {**self.default_context, **dict(context or {})}
        if session_id is not None:
            merged["session_id"] = session_id
        data: Dict[str, Any] = {
            "event_type": event_type,
            "user_id": user_id,
            "external_product_id": product_id,
            "context": merged,
        }
        if occurred_at is not None:
            data["occurred_at"] = occurred_at
        if event_id is not None:
            data["event_id"] = event_id
        return coerce_input(EventInput, data)

    # -- typed helpers --------------------------------------------------------

    def view(self, user_id: Optional[str], product_id: str, **options: Any) -> EventInput:
        return self._typed(EventType.VIEW, user_id, product_id, options)

    def click(self, user_id: Optional[str], product_id: str, **options: Any) -> EventInput:
        return self._typed(EventType.CLICK, user_id, product_id, options)

    def add_to_cart(
        self,
        user_id: Optional[str],
        product_id: str,
        *,
        quantity: int = 1,
        price: Optional[Number] = None,
        **options: Any,
    ) -> EventInput:
        _positive_quantity(quantity)
        extra = {"quantity": quantity, **({"price": str(price)} if price is not None else {})}
        return self._typed(EventType.ADD_TO_CART, user_id, product_id, options, extra)

    def remove_from_cart(
        self, user_id: Optional[str], product_id: str, *, quantity: int = 1, **options: Any
    ) -> EventInput:
        _positive_quantity(quantity)
        return self._typed(
            EventType.REMOVE_FROM_CART, user_id, product_id, options, {"quantity": quantity}
        )

    def purchase(
        self,
        user_id: Optional[str],
        product_id: str,
        *,
        order_id: Optional[str] = None,
        line: Optional[Union[int, str]] = None,
        quantity: int = 1,
        price: Optional[Number] = None,
        currency: Optional[str] = None,
        **options: Any,
    ) -> EventInput:
        """A purchased order line.

        With ``order_id`` the event ID is derived from ``(order_id, line or
        product_id)``, so replaying the same order webhook never double-counts.
        """

        _positive_quantity(quantity)
        extra: Dict[str, Any] = {"quantity": quantity}
        if order_id is not None:
            extra["order_id"] = order_id
            options.setdefault(
                "event_id",
                deterministic_id(
                    "purchase", order_id, line if line is not None else product_id, prefix="evt"
                ),
            )
        if price is not None:
            extra["price"] = str(price)
        if currency is not None:
            extra["currency"] = currency
        return self._typed(EventType.PURCHASE, user_id, product_id, options, extra)

    def rating(
        self,
        user_id: Optional[str],
        product_id: str,
        rating: Union[int, float],
        *,
        max_rating: Union[int, float] = 5,
        **options: Any,
    ) -> EventInput:
        if not 0 <= rating <= max_rating:
            raise InputValidationError(f"rating must be between 0 and {max_rating}")
        extra = {"rating": rating, "max_rating": max_rating}
        return self._typed(EventType.RATING, user_id, product_id, options, extra)

    def search(self, user_id: Optional[str], query: str, **options: Any) -> EventInput:
        return self._typed(EventType.SEARCH, user_id, None, options, {"query": query})

    def add_to_wishlist(
        self, user_id: Optional[str], product_id: str, **options: Any
    ) -> EventInput:
        return self._typed(EventType.ADD_TO_WISHLIST, user_id, product_id, options)

    def _typed(
        self,
        event_type: EventType,
        user_id: Optional[str],
        product_id: Optional[str],
        options: Dict[str, Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> EventInput:
        allowed = {"session_id", "context", "occurred_at", "event_id"}
        unknown = set(options) - allowed
        if unknown:
            raise InputValidationError(
                f"Unexpected argument(s) {sorted(unknown)}; "
                "put custom attributes in context={...}"
            )
        context = {**(extra or {}), **dict(options.get("context") or {})}
        return self.build(
            event_type,
            user_id=user_id,
            product_id=product_id,
            session_id=options.get("session_id"),
            context=context,
            occurred_at=options.get("occurred_at"),
            event_id=options.get("event_id"),
        )


def _positive_quantity(quantity: int) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise InputValidationError("quantity must be a positive integer")
