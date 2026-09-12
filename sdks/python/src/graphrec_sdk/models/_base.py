from __future__ import annotations

from typing import Generic, Iterator, List, TypeVar, Union, overload

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["GraphRecModel", "InputModel", "ItemList"]

ItemT = TypeVar("ItemT")


class GraphRecModel(BaseModel):
    """Base for API responses.

    Unknown fields are kept (``model_extra``) so a newer server never breaks an
    older SDK.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True, protected_namespaces=())


class InputModel(BaseModel):
    """Base for request payloads. Unknown fields are rejected to catch typos early."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, protected_namespaces=())


class ItemList(GraphRecModel, Generic[ItemT]):
    """A list response. Iterate, index or slice it directly, or use ``.items``."""

    items: List[ItemT] = Field(default_factory=list)

    def __iter__(self) -> Iterator[ItemT]:  # type: ignore[override]
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @overload
    def __getitem__(self, index: int) -> ItemT: ...

    @overload
    def __getitem__(self, index: slice) -> List[ItemT]: ...

    def __getitem__(self, index: Union[int, slice]) -> Union[ItemT, List[ItemT]]:
        return self.items[index]
