"""What "eligible" means, and the one place it is decided.

The rule itself is **not here.** It is in the database, in
`product_ineligibility(is_active, availability, deleted_at)` (migration 0007),
because it has to be the same rule in three places at once:

  * the partial index `ix_products_eligible`, which the serving path walks;
  * the serving path's `WHERE`, which must match that index;
  * the API's `served` / `ineligible` badge (dc.html L1307).

A Python copy of the rule would be a fourth, and the drift would be silent — the
catalogue screen would say a product is served while the recommender never
returned it, and nothing would error. So this module holds only what SQL cannot:
the *wording* for each reason the function can return.

`Product.ineligibility` in `graphrec/db/models/catalog.py` has a Python branch as
well, for an object already loaded. That is a genuine second implementation and
it is treated as one: `tests/catalog/test_eligibility.py` evaluates every
combination of the three inputs through both and requires them to agree.
"""

from __future__ import annotations

from enum import StrEnum


class Ineligibility(StrEnum):
    """The reasons `product_ineligibility` can return.

    Ordered as the function orders them. A product that is both inactive and out
    of stock is reported as **inactive**, because that is the state the tenant
    chose and the one they can act on; stock is a fact about the world.
    """

    #: Retention or tenant deletion. Not `:disable`, which sets `is_active`.
    REMOVED = "product_removed"
    INACTIVE = "product_inactive"
    OUT_OF_STOCK = "product_out_of_stock"


#: dc.html L683 and L686, verbatim, em dash included. These are the prototype's
#: `product.why` strings — not error copy, because nothing failed: they explain a
#: state the tenant put the product in. `tests/contract/test_error_copy_parity.py`
#: pins them against the prototype anyway, for the same reason it pins the rest.
EXCLUSION_COPY: dict[Ineligibility, str] = {
    Ineligibility.OUT_OF_STOCK: "Out of stock — excluded from serving",
    Ineligibility.INACTIVE: "Inactive — excluded from serving",
    # (derived) — the prototype has no route that renders a removed product,
    # because a removed product is not in any list it draws.
    Ineligibility.REMOVED: "Removed — excluded from serving",
}


def exclusion_reason(code: str | None) -> str | None:
    """The sentence the console renders under the title, or `None` if it serves.

    The console sets `sub: p.eligible ? '' : p.why` (L1302), so an eligible
    product carries no explanation at all rather than an empty-string one.
    """
    if code is None:
        return None
    return EXCLUSION_COPY[Ineligibility(code)]


__all__ = ["EXCLUSION_COPY", "Ineligibility", "exclusion_reason"]
