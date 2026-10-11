"""Reel API routes for running and querying capability proofs."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..dependencies import services
from ..graphrec import Services
from ..proof import ProofReport, get_latest_proof_report, run_proof_battery
from ..schemas import Envelope

router = APIRouter(prefix="/proof", tags=["proof"])


class RunProofIn(BaseModel):
    profile: str = "full"


@router.post("/run", response_model=Envelope[ProofReport])
async def trigger_proof_battery(
    body: Optional[RunProofIn] = None,
    svc: Services = Depends(services),
):
    profile = body.profile if body else "full"
    report = await run_proof_battery(svc, profile=profile)
    return Envelope(data=report)


@router.get("/latest", response_model=Envelope[Optional[ProofReport]])
async def latest_proof_report(svc: Services = Depends(services)):
    report = get_latest_proof_report()
    if report is None:
        # If no run has executed yet in this process, run one on-demand in tiny profile or return null
        return Envelope(data=None)
    return Envelope(data=report)
