"""Runner and report coordinator for GraphRec capability proofs."""

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional

from .battery import ProofBattery
from .schemas import ProofBatterySummary, ProofReport

logger = logging.getLogger("reel.proof")

_LATEST_REPORT: Optional[ProofReport] = None


async def run_proof_battery(services: Any, profile: str = "full") -> ProofReport:
    global _LATEST_REPORT
    run_id = f"proof-{secrets.token_hex(4)}"
    started_at = datetime.now(timezone.utc)
    t0 = time.perf_counter()

    battery = ProofBattery(services, run_id=run_id, profile=profile)
    checks = await battery.run_all()

    total_dur_ms = (time.perf_counter() - t0) * 1000
    completed_at = datetime.now(timezone.utc)

    passed_count = sum(1 for c in checks if c.passed)
    failed_count = len(checks) - passed_count
    rate = passed_count / len(checks) if checks else 0.0

    summary = ProofBatterySummary(
        run_id=run_id,
        profile=profile,
        started_at=started_at,
        completed_at=completed_at,
        total_checks=len(checks),
        passed_checks=passed_count,
        failed_checks=failed_count,
        success_rate=round(rate, 4),
        total_duration_ms=round(total_dur_ms, 2),
    )

    report = ProofReport(summary=summary, checks=checks)
    _LATEST_REPORT = report

    logger.info(
        "Proof battery %s completed in %.2fms: %d/%d passed (%.1f%%)",
        run_id,
        total_dur_ms,
        passed_count,
        len(checks),
        rate * 100,
    )
    return report


def get_latest_proof_report() -> Optional[ProofReport]:
    return _LATEST_REPORT
