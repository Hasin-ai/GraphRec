from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from graphrec_core.settings import Settings, get_settings
from graphrec_core.version import __version__

router = APIRouter(prefix="/v1", tags=["meta"])


class MetaFeatures(BaseModel):
    #: Synthetic placeholder training and manual model registration (development only).
    development_placeholders: bool


class MetaResponse(BaseModel):
    """Public product metadata: one version shared by API, console and SDK."""

    product: str = "GraphRec"
    version: str
    environment: str
    features: MetaFeatures


@router.get("/meta", response_model=MetaResponse)
def get_meta(settings: Settings = Depends(get_settings)) -> MetaResponse:
    return MetaResponse(
        version=__version__,
        environment=settings.graphrec_env,
        features=MetaFeatures(development_placeholders=not settings.is_production),
    )
