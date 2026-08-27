"""The catalogue, on the control plane.

One method, because one is what an integration needs: the per-product CRUD on
`/v1/products` is session-realm and `[DEV]`-marked — it is the console's, for a
person fixing one row. A nightly sync from a tenant's own backend runs at three
in the morning and cannot require anyone to be signed in.

``mode="upsert_and_disable_missing"`` treats the payload as the entire catalogue
and disables anything absent from it. That is the right mode for a full export
and a catastrophic one for a partial page, which is why it is not the default
and why this sentence is here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._spec import CallOptions, Spec
from .._validate import build
from ..models import CatalogSync, ProductInput, Submission, SyncMode
from .submissions import decode_submission

if TYPE_CHECKING:
    from ..transport import AsyncTransport, Transport

_ProductArg = ProductInput | dict[str, Any]


def sync_spec(
    *,
    sync_id: str,
    products: list[_ProductArg],
    mode: SyncMode | None = None,
    options: CallOptions | None = None,
) -> Spec:
    request = build(CatalogSync, "A catalogue sync", sync_id=sync_id, products=products, mode=mode)
    return Spec(
        "POST",
        "/v1/products:bulk-upsert",
        request.model_dump(mode="json", exclude_none=True),
        idempotent=True,
        options=options,
    )


class Catalog:
    """The catalogue, blocking."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def sync(
        self,
        *,
        sync_id: str,
        products: list[_ProductArg],
        mode: SyncMode | None = None,
        options: CallOptions | None = None,
    ) -> Submission:
        """Send up to 5,000 products, accepted for processing.

        Returns the submission at `202`, before any of it has been applied. A
        repeat of the same `sync_id` returns the original submission unchanged.
        """
        return decode_submission(
            self._transport.send(
                sync_spec(sync_id=sync_id, products=products, mode=mode, options=options)
            )
        )


class AsyncCatalog:
    """The catalogue, awaited."""

    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport

    async def sync(
        self,
        *,
        sync_id: str,
        products: list[_ProductArg],
        mode: SyncMode | None = None,
        options: CallOptions | None = None,
    ) -> Submission:
        """Send up to 5,000 products, accepted for processing.

        Returns the submission at `202`, before any of it has been applied. A
        repeat of the same `sync_id` returns the original submission unchanged.
        """
        return decode_submission(
            await self._transport.send(
                sync_spec(sync_id=sync_id, products=products, mode=mode, options=options)
            )
        )
