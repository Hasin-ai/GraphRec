"""Standalone CLI to execute the GraphRec Capability Proof Battery (P1–P19).

Usage:
    python scripts/prove_graphrec.py --profile full
    python scripts/prove_graphrec.py --profile tiny --output-json report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add package root to sys.path
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from app.config import get_settings
from app.graphrec import build_services
from app.proof.runner import run_proof_battery


def print_table(report) -> None:
    print("\n" + "=" * 90)
    print(f" GRAPHREC CAPABILITY PROOF BATTERY — RUN {report.summary.run_id} ({report.summary.profile.upper()})")
    print("=" * 90)
    print(f"{'ID':<5} | {'Capability':<44} | {'Status':<6} | {'Time (ms)':<9} | Detail")
    print("-" * 90)

    for c in report.checks:
        status = "PASS" if c.passed else "FAIL"
        time_str = f"{c.duration_ms:.1f}"
        detail_snippet = c.detail or ""
        if len(detail_snippet) > 28:
            detail_snippet = detail_snippet[:25] + "..."
        print(f"{c.id:<5} | {c.name[:44]:<44} | {status:<6} | {time_str:>9} | {detail_snippet}")

    print("=" * 90)
    summary = report.summary
    rate_pct = summary.success_rate * 100
    print(f"SUMMARY: {summary.passed_checks}/{summary.total_checks} passed ({rate_pct:.1f}%) in {summary.total_duration_ms:.1f}ms")
    print("=" * 90 + "\n")


async def run_cli(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.base_url:
        settings.graphrec_base_url = args.base_url

    services = build_services(settings)
    try:
        report = await run_proof_battery(services, profile=args.profile)
        print_table(report)

        if args.output_json:
            out_file = Path(args.output_json)
            out_file.write_text(json.dumps(report.model_dump(), indent=2, default=str), encoding="utf-8")
            print(f"Wrote full JSON report to {out_file.resolve()}")

        return 0 if report.summary.failed_checks == 0 else 1
    finally:
        await services.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=["tiny", "full"], default="full", help="verification profile")
    parser.add_argument("--base-url", default=None, help="override GraphRec API URL")
    parser.add_argument("--output-json", default=None, help="path to save JSON proof report")
    args = parser.parse_args()

    return asyncio.run(run_cli(args))


if __name__ == "__main__":
    sys.exit(main())
