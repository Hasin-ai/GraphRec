/** Event types the API accepts (graphrec_core/schemas/events.py EVENT_TYPES).
 * tests/test_event_types_contract.py fails if the two lists drift apart. */
export const EVENT_TYPES = ["view", "click", "add_to_cart", "remove_from_cart", "purchase", "rating", "search", "add_to_wishlist"] as const;
