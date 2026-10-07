from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Query

from ..dependencies import services
from ..errors import StoreError
from ..graphrec import Services
from ..schemas import Envelope, Film, FilmPage, Genre, Tag

router = APIRouter(tags=["films"])


@router.get("/genres", response_model=Envelope[List[Genre]])
async def genres(svc: Services = Depends(services)):
    return Envelope(data=[Genre(name=n, films=c) for n, c in svc.films.genres])


@router.get("/tags", response_model=Envelope[List[Tag]])
async def tags(limit: int = Query(default=40, ge=1, le=500), svc: Services = Depends(services)):
    """The most widely used community tags across the catalogue."""
    return Envelope(data=[Tag(name=n, films=c) for n, c in svc.films.tags[:limit]])


@router.get("/films", response_model=Envelope[FilmPage])
async def browse(
    genre: Optional[str] = Query(default=None, max_length=40),
    tag: Optional[str] = Query(default=None, max_length=60),
    q: Optional[str] = Query(default=None, max_length=80),
    sort: Literal["popular", "newest", "oldest", "title"] = "popular",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=60),
    svc: Services = Depends(services),
):
    if genre and genre not in dict(svc.films.genres):
        raise StoreError(422, "unknown_genre", f"Unknown genre '{genre}'.")
    items, total = svc.films.browse(genre=genre, tag=(tag or "").strip() or None, query=(q or "").strip() or None,
                                    sort=sort, offset=offset, limit=limit)
    return Envelope(data=FilmPage(items=[Film(**f) for f in items], total=total, offset=offset, limit=limit))


@router.get("/films/{film_id}", response_model=Envelope[Film])
async def film(film_id: str, svc: Services = Depends(services)):
    found = svc.films.get(film_id)
    if not found:
        raise StoreError(404, "not_found", "That film is not in this store.")
    return Envelope(data=Film(**found))
