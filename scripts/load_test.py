"""NR-NF-04 load test: concurrent storefront traffic against a running GraphRec API.

    python -m scripts.load_test --base-url http://localhost:8010 --concurrency 16 --duration 60 \
        --out docs/load/latest.json

What it does
------------
1. Provisions a fresh tenant through the public API (registration, password setup),
   raises its plan limits with the platform bootstrap token (development only, or
   pass --tenant-token/--api-key for an existing tenant), loads a catalog and an
   interaction history, and creates a storefront API key.
2. Optionally trains and activates a DGSR model (``--train``; needs the worker).
3. Runs ``--concurrency`` closed-loop virtual shoppers for ``--duration`` seconds.
   Each request picks, by weight, one of:
     * 70 %  POST /v1/recommendations   (known shopper or a short anonymous session)
     * 20 %  POST /v1/events            (a view)
     * 10 %  GET  /v1/products/{id}
4. Reports per-operation throughput, latency percentiles and errors, split into
   expected limits (429) and failures (5xx, timeouts, transport errors), and
   writes the JSON report.

No external load tool is needed (httpx is already a dependency of the SDK and the
tests); see docs/DECISIONS.md D-15.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx

OPERATIONS = (("recommend", 70), ("event", 20), ("product", 10))


@dataclass
class Stats:
    latencies: list[float] = field(default_factory=list)
    ok: int = 0
    limited: int = 0      # 429: an expected, plan-driven outcome
    failed: int = 0       # 5xx, timeouts, transport errors
    timeouts: int = 0     # client-side timeouts (included in failed)
    other: int = 0        # unexpected 4xx
    strategies: dict[str, int] = field(default_factory=dict)
    examples: list[str] = field(default_factory=list)   # first unexpected responses, for diagnosis

    def summary(self, seconds: float) -> dict:
        lat = sorted(self.latencies)
        def pct(p: float) -> float | None:
            return round(lat[min(len(lat) - 1, int(p * len(lat)))] * 1000, 1) if lat else None
        total = self.ok + self.limited + self.failed + self.other
        return {"requests": total, "throughput_rps": round(total / seconds, 1), "ok": self.ok,
                "rate_limited_429": self.limited, "failed": self.failed, "timeouts": self.timeouts, "unexpected_4xx": self.other,
                "error_rate": round(self.failed / total, 4) if total else 0.0,
                "latency_ms": {"p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99),
                               "mean": round(statistics.fmean(lat) * 1000, 1) if lat else None,
                               "max": round(lat[-1] * 1000, 1) if lat else None},
                **({"strategies": self.strategies} if self.strategies else {}),
                **({"unexpected_examples": self.examples} if self.examples else {})}


async def _json(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        raise SystemExit(f"{response.request.method} {response.request.url.path} -> {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else {}


async def provision(client: httpx.AsyncClient, args) -> tuple[str, str, list[str], list[str]]:
    """Returns (tenant_id, api_key, product_ids, shopper_ids)."""
    tag = uuid4().hex[:10]
    tenant = await _json(await client.post("/v1/tenants", headers={"Idempotency-Key": f"load-{tag}"},
                                           json={"name": f"Load test {tag}", "admin_email": f"load-{tag}@example.org"}))
    session = await _json(await client.post("/v1/auth/setup-password",
                                            json={"setup_token": tenant["setup_token"], "password": f"Load-test-{tag}-pw!"}))
    admin = {"Authorization": f"Bearer {session['access_token']}"}
    operator = {"Authorization": f"Bearer {args.platform_token}"}
    await _json(await client.post(f"/v1/platform/tenants/{tenant['id']}/quotas", headers=operator, json={
        "reason": "NR-NF-04 load test", "overrides": {
            "recommendation_requests": 10_000_000, "requests_per_minute": 1_000_000, "concurrent_recommendation_requests": 1000,
            "accepted_events": 10_000_000, "stored_products": 100_000, "training_jobs": 10}}))
    products = [f"sku-{i:04d}" for i in range(args.products)]
    categories = ["shoes", "hats", "bags", "coats", "socks"]
    for start in range(0, len(products), 500):
        await _json(await client.post("/v1/products:bulk-upsert", headers=admin, json={"products": [
            {"external_id": p, "title": f"Product {p}", "category": categories[i % 5], "price": str(5 + i % 50)}
            for i, p in enumerate(products[start:start + 500], start)]}))
    shoppers = [f"shopper-{i:04d}" for i in range(args.shoppers)]
    rng = random.Random(7)
    base = datetime.now(timezone.utc) - timedelta(days=2)
    events = []
    for s, shopper in enumerate(shoppers):
        for i in range(8):  # a short, skewed history per shopper
            product = products[min(len(products) - 1, int(rng.paretovariate(1.2)) - 1 + (s % 7))]
            events.append({"event_id": f"seed-{s}-{i}", "event_type": "view", "user_id": shopper,
                           "external_product_id": product, "occurred_at": (base + timedelta(minutes=s * 10 + i)).isoformat()})
    for start in range(0, len(events), 1000):
        await _json(await client.post("/v1/events/batches", headers=admin, json={"events": events[start:start + 1000]}))
    if args.train:
        job = await _json(await client.post("/v1/training-jobs", headers=admin, json={
            "request_id": f"load-{tag}", "configuration": {"mode": "train", "epochs": 1}}))
        for _ in range(600):
            state = await _json(await client.get(f"/v1/training-jobs/{job['id']}", headers=admin))
            if state["status"] in {"succeeded", "failed", "cancelled"}:
                break
            await asyncio.sleep(1)
        if state["status"] != "succeeded":
            raise SystemExit(f"Training did not succeed: {state.get('failure_reason') or state['status']}")
        await _json(await client.post(f"/v1/model-versions/{state['model_version_id']}:activate", headers=admin, json={}))
    key = await _json(await client.post("/v1/api-keys", headers=admin, json={
        "name": f"load-{tag}", "scopes": ["recommendations:read", "events:write", "catalog:read"]}))
    return tenant["id"], key.get("secret") or key.get("api_key"), products, shoppers


async def shopper_loop(client, key, products, shoppers, deadline, stats, rng, timeout):
    headers = {"Authorization": f"ApiKey {key}", "Accept": "application/json"}
    names = [name for name, _ in OPERATIONS]
    weights = [w for _, w in OPERATIONS]
    while time.monotonic() < deadline:
        op = rng.choices(names, weights)[0]
        started = time.perf_counter()
        try:
            if op == "recommend":
                body = {"top_n": 10}
                if rng.random() < 0.8:
                    body["user_id"] = rng.choice(shoppers)
                else:
                    body["context"] = {"session_id": f"anon-{rng.randrange(10_000)}",
                                       "recent_product_ids": rng.sample(products[:50], 2)}
                response = await client.post("/v1/recommendations", headers=headers, json=body, timeout=timeout)
            elif op == "event":
                response = await client.post("/v1/events", headers=headers, timeout=timeout, json={
                    "event_id": f"load-{uuid4().hex}", "event_type": "view", "user_id": rng.choice(shoppers),
                    "external_product_id": rng.choice(products), "occurred_at": datetime.now(timezone.utc).isoformat()})
            else:
                response = await client.get(f"/v1/products/{rng.choice(products)}", headers=headers, timeout=timeout)
        except httpx.TimeoutException:
            stats[op].failed += 1
            stats[op].timeouts += 1
            continue
        except httpx.TransportError:
            stats[op].failed += 1
            continue
        elapsed = time.perf_counter() - started
        s = stats[op]
        if response.status_code < 300:
            s.ok += 1
            s.latencies.append(elapsed)
            if op == "recommend":
                strategy = response.json().get("strategy", "?")
                s.strategies[strategy] = s.strategies.get(strategy, 0) + 1
        elif response.status_code == 429:
            s.limited += 1
        elif response.status_code >= 500:
            s.failed += 1
        else:
            s.other += 1
            if len(s.examples) < 3:
                s.examples.append(f"{response.status_code} {response.text[:160]}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("GRAPHREC_BASE_URL", "http://localhost:8010"))
    parser.add_argument("--platform-token", default=os.environ.get("PLATFORM_ADMIN_TOKEN"))
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--duration", type=int, default=60, help="seconds of measured load")
    parser.add_argument("--warmup", type=int, default=10, help="seconds of unmeasured load first")
    parser.add_argument("--products", type=int, default=1000)
    parser.add_argument("--shoppers", type=int, default=300)
    parser.add_argument("--train", action="store_true", help="train and activate a DGSR model first (needs the worker)")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", help="write the JSON report here")
    args = parser.parse_args()
    if not args.platform_token:
        print("Set PLATFORM_ADMIN_TOKEN (development) so the test tenant's limits can be raised.", file=sys.stderr)
        return 2
    limits = httpx.Limits(max_connections=args.concurrency + 4, max_keepalive_connections=args.concurrency + 4)
    async with httpx.AsyncClient(base_url=args.base_url, limits=limits, timeout=60) as client:
        meta = (await client.get("/v1/meta")).json()
        tenant_id, key, products, shoppers = await provision(client, args)
        rng = random.Random(11)
        warm = {name: Stats() for name, _ in OPERATIONS}
        deadline = time.monotonic() + args.warmup
        await asyncio.gather(*(shopper_loop(client, key, products, shoppers, deadline, warm, random.Random(rng.random()), args.timeout)
                               for _ in range(args.concurrency)))
        stats = {name: Stats() for name, _ in OPERATIONS}
        started = time.monotonic()
        deadline = started + args.duration
        await asyncio.gather(*(shopper_loop(client, key, products, shoppers, deadline, stats, random.Random(rng.random()), args.timeout)
                               for _ in range(args.concurrency)))
        seconds = time.monotonic() - started
    combined = Stats()
    for s in stats.values():
        combined.latencies += s.latencies
        combined.ok += s.ok; combined.limited += s.limited; combined.failed += s.failed; combined.other += s.other
        combined.timeouts += s.timeouts
    report = {
        "requirement": "NR-NF-04",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "graphrec_version": meta.get("version"), "environment": meta.get("environment"),
        "target": args.base_url, "tenant_id": tenant_id,
        "load": {"concurrency": args.concurrency, "duration_seconds": round(seconds, 1), "warmup_seconds": args.warmup,
                 "mix": dict(OPERATIONS), "products": args.products, "shoppers": args.shoppers, "trained_model": args.train},
        "host": {"cpus": os.cpu_count(), "platform": platform.platform(), "python": platform.python_version()},
        "overall": combined.summary(seconds),
        "operations": {name: s.summary(seconds) for name, s in stats.items()},
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0 if combined.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
