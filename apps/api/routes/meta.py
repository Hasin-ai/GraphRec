from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from graphrec_core.database.models import PricingPlan
from graphrec_core.database.session import get_db

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


class PublicPlan(BaseModel):
    code: str
    name: str
    limits: dict[str, Any]


class PublicPlanList(BaseModel):
    """A-25: the active plans and their current limits, as configured by the operator."""

    items: list[PublicPlan]


@router.get("/plans", response_model=PublicPlanList)
def list_public_plans(db: Session = Depends(get_db)) -> PublicPlanList:
    plans = db.scalars(select(PricingPlan).where(PricingPlan.is_active.is_(True)).order_by(PricingPlan.code)).all()
    return PublicPlanList(items=[PublicPlan(code=p.code, name=p.name, limits=p.limits) for p in plans])
