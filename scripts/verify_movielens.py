"""Repeatable SRS acceptance probe using real MovieLens weights and API calls.

Run in the API container with /movielens (read-only) and /reports mounted.
Creates isolated demo tenants. Never reads or changes existing tenant records.
"""
from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import numpy as np


def main():
    tag = uuid4().hex[:10]
    base = os.environ.get("GRAPHREC_API_URL", "http://api:8000")
    client = httpx.Client(base_url=base, timeout=180, headers={"Accept": "application/json"})
    records = []
    passwords = {}

    def check(name, condition, detail=None):
        records.append({"check": name, "passed": bool(condition), "detail": detail})
        print(f"{'PASS' if condition else 'FAIL'} {name}", flush=True)
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    def call(method, path, body=None, token=None, expected=200, scheme="Bearer"):
        headers = {"Authorization": f"{scheme} {token}"} if token else {}
        if path == "/v1/tenants":
            headers["Idempotency-Key"] = str(uuid4())
        response = client.request(method, path, json=body, headers=headers)
        if response.status_code != expected:
            raise AssertionError(f"{method} {path}: expected {expected}, got {response.status_code}: {response.text[:500]}")
        return response.json()

    def tenant(label):
        email = f"movielens-{label}-{tag}@example.org"
        password = f"MovieLens-demo-{uuid4().hex[:16]}!"
        created = call("POST", "/v1/tenants", {"name": f"MovieLens {label} {tag}", "admin_email": email}, expected=201)
        auth = call("POST", "/v1/auth/setup-password", {"setup_token": created["setup_token"], "password": password})
        passwords[label] = {"email": email, "password": password, "tenant_id": created["id"]}
        return created, auth["access_token"]

    report = Path(os.environ.get("REPORT_DIR", "/reports"))
    report.mkdir(parents=True, exist_ok=True)
    try:
        a, token = tenant("Cinema-A")
        b, other = tenant("Cinema-B")
        operator = os.environ["PLATFORM_ADMIN_TOKEN"]
        call("POST", f"/v1/platform/tenants/{a['id']}/quotas", {"overrides": {"stored_products": 10000, "training_jobs": 10}}, operator)
        artifact = Path("/artifacts/dgsr_movielens_32m")
        maps = json.loads((artifact / "id_maps.json").read_text())
        titles = {}
        with Path("/movielens/ml-32m/ml-32m/movies.csv").open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                titles[row["movieId"]] = row
        products = [{"external_id": item, "title": titles[item]["title"], "category": titles[item]["genres"], "price": "0", "metadata": {"source": "MovieLens 32M"}} for item in maps["item_ids"]]
        for offset in range(0, len(products), 100):
            result = call("POST", "/v1/products:bulk-upsert", {"products": products[offset:offset + 100]}, token)
            check(f"catalog batch {offset // 100 + 1}", result.get("rejected_count", result.get("failed", 0)) == 0)
        check("full model catalog imported", call("GET", "/v1/products?limit=1", token=token)["total"] == len(products), len(products))
        with np.load(artifact / "interactions.npz", allow_pickle=False) as arrays:
            rows = np.flatnonzero(np.isin(arrays["users"], [0, 1, 2]))
            # Complete histories for three trained shoppers, without relabelling
            # held-out data as new training. The checkpoint stays unchanged.
            events = [{"event_id": f"ml-{int(i)}", "event_type": "view", "user_id": maps["user_ids"][int(arrays['users'][i])], "external_product_id": maps["item_ids"][int(arrays['items'][i])], "occurred_at": datetime.fromtimestamp(int(arrays['times'][i]), timezone.utc).isoformat()} for i in rows]
        for offset in range(0, len(events), 50):
            result = call("POST", "/v1/events/batches", {"events": events[offset:offset + 50]}, token)
            check(f"history batch {offset // 50 + 1}", result["rejected_count"] == 0)
        snapshot = call("POST", "/v1/datasets/snapshots", {}, token)
        job = call("POST", "/v1/training-jobs", {"dataset_snapshot_id": snapshot['id'], "configuration": {"pretrained_artifact": "dgsr_movielens_32m"}}, token)
        check("verified MovieLens checkpoint imports", job["status"] == "succeeded", job.get("failure_reason"))
        version = job["model_version_id"]
        model = call("GET", f"/v1/model-versions/{version}", token=token)
        check("real validation metrics retained", model["metrics"].get("validation", {}).get("NDCG@10", 0) > 0, model["metrics"].get("validation"))
        call("POST", f"/v1/model-versions/{version}:activate", token=token)
        request = {"request_id": f"srs-{tag}", "user_id": maps["user_ids"][0], "top_n": 10}
        result = call("POST", "/v1/recommendations", request, token)
        check("real DGSR serves known shopper", result["strategy"] == "personalized" and not result["fallback_used"] and len(result["items"]) == 10, {k: result[k] for k in ('strategy', 'model_version_id')})
        replay = call("POST", "/v1/recommendations", request, token)
        check("recommendation request replay is stable", replay == result)
        call("POST", "/v1/recommendations", {**request, "top_n": 9}, token, expected=409)
        known = call("POST", "/v1/recommendations", {"user_id": maps["user_ids"][0], "top_n": 10}, token)
        check("ranking is deterministic", result['items'] == known['items'])
        session = call("POST", "/v1/recommendations/session", {"top_n": 5, "context": {"recent_product_ids": [events[-1]["external_product_id"]]}}, token)
        check("anonymous session serving works", session['strategy'] == 'session' and len(session['items']) == 5, session['strategy'])
        feedback = {"event_id": f"impression-{tag}", "request_id": result['request_id'], "items": result['items']}
        first = call("POST", "/v1/feedback/impressions", feedback, token)
        duplicate = call("POST", "/v1/feedback/impressions", feedback, token)
        check("feedback is persisted exactly once", first['accepted'] and not first['duplicate'] and duplicate['duplicate'])
        item = result['items'][0]
        click = {"event_id": f"click-{tag}", "request_id": result['request_id'], "impression_event_id": feedback['event_id'], **item}
        call("POST", "/v1/feedback/clicks", click, token)
        call("POST", "/v1/feedback/conversions", {"event_id": f"sale-{tag}", "request_id": result['request_id'], **item, "value": 9.99}, token)
        call("POST", "/v1/feedback/clicks", {**click, "event_id": 'wrong-position', "position": 99}, token, expected=422)
        call("POST", "/v1/feedback/impressions", feedback, other, expected=404)
        call("GET", f"/v1/model-versions/{version}", token=other, expected=404)
        call("POST", f"/v1/model-versions/{version}:activate", token=other, expected=404)
        check("foreign models and recommendation feedback are rejected", True)
        disabled = item['external_product_id']
        call("POST", f"/v1/products/{disabled}:disable", token=token)
        after = call("POST", "/v1/recommendations", {"user_id": maps['user_ids'][0], "top_n": 10}, token)
        check("disabled movie never returned", disabled not in [i['external_product_id'] for i in after['items']])
        call("POST", "/v1/recommendations", request, token, expected=409)
        check("replay cannot reintroduce a disabled movie", True)
        corrupt = call("POST", "/v1/model-versions", {"version_tag": f"bad-{tag}", "model_type": "dgsr", "artifact_uri": "file:///artifacts/missing", "metrics": {}}, token)
        call("POST", f"/v1/model-versions/{corrupt['id']}:activate", token=token, expected=422)
        check("failed activation preserves active version", call("GET", "/v1/deployment", token=token)['active_model_version_id'] == version)
        call("POST", f"/v1/model-versions/{corrupt['id']}:archive", token=token)
        call("POST", f"/v1/model-versions/{corrupt['id']}:activate", token=token, expected=409)
        timings = []
        for _ in range(20):
            start = time.perf_counter()
            call("POST", "/v1/recommendations", {"user_id": maps['user_ids'][1], "top_n": 10}, token)
            timings.append((time.perf_counter() - start) * 1000)
        records.append({"check": "warm sequential request latency (20 requests, local container network)", "p95_ms": round(float(np.percentile(timings, 95)), 1), "p50_ms": round(float(np.median(timings)), 1)})
        # Keep a usable administrator and developer for manual frontend inspection.
        email = f"movielens-developer-{tag}@example.org"
        password = f"MovieLens-dev-{uuid4().hex[:16]}!"
        invited = call("POST", "/v1/tenant/users", {"email": email, "role": "tenant_developer", "display_name": "MovieLens integration developer"}, token, expected=201)
        call("POST", "/v1/auth/setup-password", {"setup_token": invited['setup_token'], "password": password})
        passwords['Developer'] = {"email": email, "password": password, "tenant_id": a['id']}
        records.append({"model_version_id": version, "tenant_id": a['id'], "catalog_items": len(products), "imported_events": len(events)})
    finally:
        (report / "movielens-acceptance.json").write_text(json.dumps(records, indent=2))
        (report / "demo-accounts.json").write_text(json.dumps(passwords, indent=2))


if __name__ == '__main__':
    main()

