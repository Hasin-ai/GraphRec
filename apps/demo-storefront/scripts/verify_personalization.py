"""The model-proof gate: does the live serving path personalise per user?

    python scripts/verify_personalization.py [--top-n 5] [--exclude sku ...]

Requests the same Top-N for Maya, Noah and Lina (twice each), then checks:

1. a model version is returned;
2. no known shopper gets the catalog fallback;
3. repeating a request gives the same ordering;
4. shoppers with different histories get different rankings;
5. excluded and inactive products never appear;
6. a no-history visitor receives an explicitly labelled fallback (reported, not fatal).

Exit code 0 only when every check passes. Writes ``verification-result.json``
(git-ignored) with the checked model version. It never sets MODEL_PROOF_VERIFIED
itself: a human copies the version into .env after reading the report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from _common import PACKAGE_DIR, env, load_env, require, step

from fixtures.personas import KNOWN_PERSONAS, PERSONAS
from graphrec_sdk import AsyncGraphRec

RESULT_FILE = PACKAGE_DIR / "verification-result.json"


async def main(argv=None) -> int:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=env("GRAPHREC_BASE_URL", "http://localhost:8010"))
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--exclude", nargs="*", default=[])
    args = parser.parse_args(argv)
    api_key = env("GRAPHREC_SEED_API_KEY") or require("GRAPHREC_API_KEY")

    failures = []
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "top_n": args.top_n, "exclude": args.exclude, "personas": {}}

    async with AsyncGraphRec(base_url=args.base_url, api_key=api_key, use_env=False) as client:
        inactive = {p.external_id for p in await client.products.list() if not (p.is_active and p.availability_status == "available")}
        rankings = {}
        versions = set()
        step("known shoppers, same request twice")
        for key in KNOWN_PERSONAS:
            persona = PERSONAS[key]
            first = await client.recommendations.get(user_id=persona.user_id, top_n=args.top_n, exclude_product_ids=args.exclude)
            second = await client.recommendations.get(user_id=persona.user_id, top_n=args.top_n, exclude_product_ids=args.exclude)
            ids = first.product_ids
            rankings[key] = ids
            repeatable = ids == second.product_ids
            if first.model_version_id:
                versions.add(str(first.model_version_id))
            report["personas"][key] = {"ids": ids, "strategy": first.strategy, "fallback_used": first.fallback_used, "model_version_id": str(first.model_version_id) if first.model_version_id else None, "repeatable": repeatable}
            print(f"  {persona.name:<6} strategy={first.strategy:<17} fallback={first.fallback_used!s:<5} version={first.model_version_id} repeatable={repeatable} -> {ids}")
            if first.fallback_used:
                failures.append(f"{persona.name} received the catalog fallback")
            if not repeatable:
                failures.append(f"{persona.name}: repeating the request changed the ordering")
            leaked = [i for i in ids if i in inactive or i in set(args.exclude)]
            if leaked:
                failures.append(f"{persona.name}: excluded or inactive products appeared: {leaked}")

        step("cold-start visitor")
        guest = await client.recommendations.for_session("sess_verify_guest", top_n=args.top_n, exclude_product_ids=args.exclude)
        report["personas"]["guest"] = {"ids": guest.product_ids, "strategy": guest.strategy, "fallback_used": guest.fallback_used}
        print(f"  guest  strategy={guest.strategy:<17} fallback={guest.fallback_used} -> {guest.product_ids}")
        if not guest.fallback_used:
            print("  note: the no-history visitor did not get an explicit fallback; the serving path treats it like a user.")

    step("similarity")
    for a, b in combinations(rankings, 2):
        sa, sb = set(rankings[a]), set(rankings[b])
        jaccard = len(sa & sb) / len(sa | sb) if sa | sb else 0.0
        print(f"  {PERSONAS[a].name} vs {PERSONAS[b].name}: overlap {len(sa & sb)}/{args.top_n}, Jaccard {jaccard:.2f}")
    distinct = len({tuple(r) for r in rankings.values()})
    print(f"  distinct orderings: {distinct} of {len(rankings)}")

    if not versions:
        failures.append("no model version was returned")
    elif len(versions) > 1:
        failures.append(f"different model versions answered: {sorted(versions)}")
    if distinct < len(rankings):
        failures.append("shoppers with different histories received identical rankings (the query is not user-specific)")

    report["model_version_id"] = next(iter(versions)) if len(versions) == 1 else None
    report["passed"] = not failures
    report["failures"] = failures
    RESULT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")

    step("result")
    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        print(f"\nProof gate NOT passed. Keep MODEL_PROOF_VERIFIED=false. Report written to {RESULT_FILE.name}.")
        return 1
    print(f"  PASS  model version {report['model_version_id']}")
    print(
        f"\nProof gate passed. To let the storefront say 'Model-backed', a human sets in .env:\n"
        f"  MODEL_PROOF_VERIFIED=true\n  MODEL_PROOF_VERSION_ID={report['model_version_id']}\n"
        f"and restarts the storefront. Report written to {RESULT_FILE.name}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
