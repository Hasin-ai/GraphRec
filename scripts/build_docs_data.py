#!/usr/bin/env python3
"""Builds web/src/docs/docsData.ts from openapi.json and SDK route specifications."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
OPENAPI_PATH = ROOT / "web" / "openapi.json"
OUTPUT_PATH = ROOT / "web" / "src" / "docs" / "docsData.ts"

with open(OPENAPI_PATH, encoding="utf-8") as f:
    spec = json.load(f)

# Grouping definitions for API reference
GROUPS = [
    {
        "id": "recommendations",
        "title": "Recommendations & Feedback",
        "description": "Real-time personalization inference, session recommendations, and attribution telemetry.",
        "tags": ["recommendations"],
    },
    {
        "id": "catalog",
        "title": "Catalog & Products",
        "description": "Product catalog synchronization, attribute indexing, and bulk upsert operations.",
        "tags": ["catalog"],
    },
    {
        "id": "events",
        "title": "Events & Ingestion",
        "description": "Shopper interaction events, batch uploads, and idempotency tracking.",
        "tags": ["events"],
    },
    {
        "id": "datasets",
        "title": "Datasets & Snapshots",
        "description": "Dataset file uploads and point-in-time training cohort snapshots.",
        "tags": ["datasets"],
    },
    {
        "id": "models",
        "title": "Models & Training",
        "description": "Sequential DGSR training jobs, model version registry, and serving lifecycle.",
        "tags": ["models", "training"],
    },
    {
        "id": "serving",
        "title": "Serving & Monitoring",
        "description": "Active deployment status, autoscaling health, latency histograms, and system probes.",
        "tags": ["deployment"],
    },
    {
        "id": "management",
        "title": "Workspace & Management",
        "description": "API key credentials, member invitations, subscription limits, usage trends, and audit trail.",
        "tags": ["api-keys", "tenant-users", "subscription", "usage", "audit", "tenants"],
    },
    {
        "id": "platform",
        "title": "Platform Operations",
        "description": "Cross-tenant administrative APIs for cluster operators.",
        "tags": ["platform"],
    },
    {
        "id": "auth",
        "title": "Authentication & Accounts",
        "description": "Member authentication, password setup, recovery, and session token rotation.",
        "tags": ["authentication", "meta"],
    },
]

TAG_TO_GROUP = {}
for g in GROUPS:
    for tag in g["tags"]:
        TAG_TO_GROUP[tag] = g["id"]


def resolve_ref(ref_str: str) -> dict:
    parts = ref_str.lstrip("#/").split("/")
    curr = spec
    for p in parts:
        curr = curr.get(p, {})
    return curr


def simplify_schema(schema: dict, depth: int = 0) -> Any:
    if depth > 4:
        return "..."
    if "$ref" in schema:
        return simplify_schema(resolve_ref(schema["$ref"]), depth + 1)
    t = schema.get("type", "object")
    if t == "object" or "properties" in schema:
        props = schema.get("properties", {})
        res = {}
        for k, v in list(props.items())[:12]:
            res[k] = simplify_schema(v, depth + 1)
        return res
    if t == "array":
        items = schema.get("items", {})
        return [simplify_schema(items, depth + 1)]
    if t == "string":
        if "enum" in schema:
            return schema["enum"][0]
        if schema.get("format") == "date-time":
            return "2026-10-10T12:00:00Z"
        if schema.get("format") == "uuid":
            return "5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5"
        return "example_string"
    if t in ("integer", "number"):
        return 1
    if t == "boolean":
        return True
    return {}


def get_scope_from_op(op: dict) -> str | None:
    # Look for scope in description or summary
    desc = op.get("description", "")
    m = re.search(r"scope[:\s]+`?([a-z_]+:[a-z_]+)`?", desc, re.IGNORECASE)
    if m:
        return m.group(1)
    # Check default scopes by path
    return None


# Map paths to SDK calls and scopes
SDK_MAPPING = {
    ("POST", "/v1/recommendations"): {
        "call": "client.storefront.recommendations.get(user_id='cus-9931', top_n=10, context={'surface': 'cart'})",
        "scope": "recommendations:read",
        "auth": "apiKey",
    },
    ("POST", "/v1/recommendations/session"): {
        "call": "client.storefront.recommendations.for_session(item_ids=['SKU-100', 'SKU-200'], top_n=10)",
        "scope": "recommendations:read",
        "auth": "apiKey",
    },
    ("POST", "/v1/feedback/impressions"): {
        "call": "client.storefront.feedback.impression(recommendation='5b1f0c9e-...', items=['SKU-100', 'SKU-200'])",
        "scope": "events:write",
        "auth": "apiKey",
    },
    ("POST", "/v1/feedback/clicks"): {
        "call": "client.storefront.feedback.click(recommendation='5b1f0c9e-...', item='SKU-100', position=1)",
        "scope": "events:write",
        "auth": "apiKey",
    },
    ("POST", "/v1/feedback/conversions"): {
        "call": "client.storefront.feedback.conversion(recommendation='5b1f0c9e-...', item='SKU-100', value=49.99)",
        "scope": "events:write",
        "auth": "apiKey",
    },
    ("POST", "/v1/events"): {
        "call": "client.storefront.events.create(event_type='view', user_id='cus-9931', external_product_id='SKU-100')",
        "scope": "events:write",
        "auth": "apiKey",
    },
    ("POST", "/v1/events/batches"): {
        "call": "client.storefront.events.create_batch(events=[{'event_type': 'view', 'user_id': 'cus-9931', 'external_product_id': 'SKU-100'}])",
        "scope": "events:write",
        "auth": "apiKey",
    },
    ("GET", "/v1/events"): {
        "call": "client.storefront.events.list(user_id='cus-9931', limit=50)",
        "scope": "events:read",
        "auth": "apiKey",
    },
    ("GET", "/v1/events/batches"): {
        "call": "client.storefront.events.list_batches(limit=20)",
        "scope": "events:read",
        "auth": "apiKey",
    },
    ("GET", "/v1/events/batches/{batch_id}"): {
        "call": "client.storefront.events.get_batch(batch_id='batch-123')",
        "scope": "events:read",
        "auth": "apiKey",
    },
    ("GET", "/v1/products"): {
        "call": "client.tenant.catalog.list(limit=50)",
        "scope": "catalog:read",
        "auth": "apiKey",
    },
    ("GET", "/v1/products/{external_id}"): {
        "call": "client.tenant.catalog.get(external_id='SKU-100')",
        "scope": "catalog:read",
        "auth": "apiKey",
    },
    ("PUT", "/v1/products/{external_id}"): {
        "call": "client.tenant.catalog.upsert(external_id='SKU-100', product={'title': 'Linen Shirt', 'price': '49.90', 'category': 'Apparel'})",
        "scope": "catalog:write",
        "auth": "apiKey",
    },
    ("PATCH", "/v1/products/{external_id}"): {
        "call": "client.tenant.catalog.update(external_id='SKU-100', patch={'price': '44.90'})",
        "scope": "catalog:write",
        "auth": "apiKey",
    },
    ("POST", "/v1/products/{external_id}:disable"): {
        "call": "client.tenant.catalog.disable(external_id='SKU-100')",
        "scope": "catalog:write",
        "auth": "apiKey",
    },
    ("POST", "/v1/products:bulk-upsert"): {
        "call": "client.tenant.catalog.bulk_upsert(products=[{'external_id': 'SKU-100', 'title': 'Linen Shirt', 'price': '49.90', 'category': 'Apparel'}])",
        "scope": "catalog:write",
        "auth": "apiKey",
    },
    ("GET", "/v1/catalog-syncs"): {
        "call": "client.tenant.catalog.list_syncs(limit=20)",
        "scope": "catalog:read",
        "auth": "apiKey",
    },
    ("GET", "/v1/catalog-syncs/{sync_id}"): {
        "call": "client.tenant.catalog.get_sync(sync_id='sync-123')",
        "scope": "catalog:read",
        "auth": "apiKey",
    },
    ("POST", "/v1/datasets/upload"): {
        "call": "client.tenant.datasets.upload(file=open('catalog.csv', 'rb'))",
        "scope": "catalog:write, events:write",
        "auth": "bearer",
    },
    ("POST", "/v1/datasets/snapshots"): {
        "call": "client.tenant.datasets.create_snapshot()",
        "scope": "training:write",
        "auth": "bearer",
    },
    ("GET", "/v1/datasets/snapshots"): {
        "call": "client.tenant.datasets.list_snapshots()",
        "scope": "training:read",
        "auth": "bearer",
    },
    ("GET", "/v1/datasets/snapshots/{snapshot_id}"): {
        "call": "client.tenant.datasets.get_snapshot(snapshot_id='snap-123')",
        "scope": "training:read",
        "auth": "bearer",
    },
    ("POST", "/v1/training-jobs"): {
        "call": "client.tenant.training_jobs.create(dataset_snapshot_id='snap-123')",
        "scope": "training:write",
        "auth": "bearer",
    },
    ("GET", "/v1/training-jobs"): {
        "call": "client.tenant.training_jobs.list()",
        "scope": "training:read",
        "auth": "bearer",
    },
    ("GET", "/v1/training-jobs/{job_id}"): {
        "call": "client.tenant.training_jobs.get(job_id='job-123')",
        "scope": "training:read",
        "auth": "bearer",
    },
    ("POST", "/v1/training-jobs/{job_id}:cancel"): {
        "call": "client.tenant.training_jobs.cancel(job_id='job-123')",
        "scope": "training:write",
        "auth": "bearer",
    },
    ("GET", "/v1/model-versions"): {
        "call": "client.tenant.model_versions.list()",
        "scope": "models:read",
        "auth": "bearer",
    },
    ("POST", "/v1/model-versions"): {
        "call": "client.tenant.model_versions.create(version_tag='v2.0', checkpoint_path='...')",
        "scope": "models:write",
        "auth": "bearer",
    },
    ("GET", "/v1/model-versions/{version_id}"): {
        "call": "client.tenant.model_versions.get(version_id='ver-123')",
        "scope": "models:read",
        "auth": "bearer",
    },
    ("POST", "/v1/model-versions/{version_id}:activate"): {
        "call": "client.tenant.model_versions.activate(version_id='ver-123')",
        "scope": "models:deploy",
        "auth": "bearer",
    },
    ("POST", "/v1/model-versions/{version_id}:rollback"): {
        "call": "client.tenant.model_versions.rollback(version_id='ver-123')",
        "scope": "models:deploy",
        "auth": "bearer",
    },
    ("POST", "/v1/model-versions/{version_id}:archive"): {
        "call": "client.tenant.model_versions.archive(version_id='ver-123')",
        "scope": "models:write",
        "auth": "bearer",
    },
    ("GET", "/v1/recommendation-policy"): {
        "call": "client.tenant.recommendation_policy.get()",
        "scope": "models:read",
        "auth": "bearer",
    },
    ("PUT", "/v1/recommendation-policy"): {
        "call": "client.tenant.recommendation_policy.update(max_category_share=0.4, freshness_boost_hours=48)",
        "scope": "models:deploy",
        "auth": "bearer",
    },
    ("GET", "/v1/retraining-policy"): {
        "call": "client.tenant.retraining_policy.get()",
        "scope": "training:read",
        "auth": "bearer",
    },
    ("PUT", "/v1/retraining-policy"): {
        "call": "client.tenant.retraining_policy.update(enabled=True, schedule_cron='0 2 * * *')",
        "scope": "training:write",
        "auth": "bearer",
    },
    ("GET", "/v1/deployment"): {
        "call": "client.tenant.deployment.get()",
        "scope": "deployments:read",
        "auth": "bearer",
    },
    ("GET", "/v1/deployment/scaling"): {
        "call": "client.tenant.deployment.scaling()",
        "scope": "deployments:read",
        "auth": "bearer",
    },
    ("GET", "/v1/metrics/summary"): {
        "call": "client.tenant.metrics.summary(window_minutes=1440)",
        "scope": "metrics:read",
        "auth": "bearer",
    },
    ("GET", "/v1/api-keys"): {
        "call": "client.tenant.api_keys.list()",
        "scope": "keys:write",
        "auth": "bearer",
    },
    ("POST", "/v1/api-keys"): {
        "call": "client.tenant.api_keys.create(name='Storefront Key', scopes=['events:write', 'recommendations:read'])",
        "scope": "keys:write",
        "auth": "bearer",
    },
    ("GET", "/v1/api-keys/{key_id}"): {
        "call": "client.tenant.api_keys.get(key_id='key-123')",
        "scope": "keys:write",
        "auth": "bearer",
    },
    ("POST", "/v1/api-keys/{key_id}/rotate"): {
        "call": "client.tenant.api_keys.rotate(key_id='key-123')",
        "scope": "keys:write",
        "auth": "bearer",
    },
    ("DELETE", "/v1/api-keys/{key_id}"): {
        "call": "client.tenant.api_keys.revoke(key_id='key-123')",
        "scope": "keys:write",
        "auth": "bearer",
    },
    ("GET", "/v1/tenant/users"): {
        "call": "client.tenant.users.list()",
        "scope": "users:write",
        "auth": "bearer",
    },
    ("POST", "/v1/tenant/users"): {
        "call": "client.tenant.users.invite(email='dev@example.com', role='tenant_developer')",
        "scope": "users:write",
        "auth": "bearer",
    },
    ("GET", "/v1/tenant/users/{user_id}"): {
        "call": "client.tenant.users.get(user_id='user-123')",
        "scope": "users:write",
        "auth": "bearer",
    },
    ("PATCH", "/v1/tenant/users/{user_id}"): {
        "call": "client.tenant.users.update(user_id='user-123', role='tenant_admin')",
        "scope": "users:write",
        "auth": "bearer",
    },
    ("DELETE", "/v1/tenant/users/{user_id}/invitation"): {
        "call": "client.tenant.users.revoke_invitation(user_id='user-123')",
        "scope": "users:write",
        "auth": "bearer",
    },
    ("POST", "/v1/tenant/users/{user_id}/invitation:resend"): {
        "call": "client.tenant.users.resend_invitation(user_id='user-123')",
        "scope": "users:write",
        "auth": "bearer",
    },
    ("GET", "/v1/subscription"): {
        "call": "client.tenant.subscription.get()",
        "scope": "billing:read",
        "auth": "apiKey",
    },
    ("GET", "/v1/usage"): {
        "call": "client.tenant.usage.get(period='current')",
        "scope": "usage:read",
        "auth": "apiKey",
    },
    ("GET", "/v1/usage/trends"): {
        "call": "client.tenant.usage.trends(granularity='day')",
        "scope": "usage:read",
        "auth": "apiKey",
    },
    ("GET", "/v1/audit"): {
        "call": "client.tenant.audit.list(limit=50)",
        "scope": "audit:read",
        "auth": "bearer",
    },
    ("GET", "/v1/tenant/status"): {
        "call": "client.tenant.account.status()",
        "scope": "status:read",
        "auth": "bearer",
    },
    ("POST", "/v1/tenants"): {
        "call": "client.tenant.auth.register(business_name='Acme', email='admin@acme.com')",
        "scope": None,
        "auth": "none",
    },
    ("POST", "/v1/auth/login"): {
        "call": "client.tenant.auth.login(email='admin@acme.com', password='...')",
        "scope": None,
        "auth": "none",
    },
    ("POST", "/v1/auth/logout"): {
        "call": "client.tenant.auth.logout()",
        "scope": None,
        "auth": "bearer",
    },
    ("POST", "/v1/auth/refresh"): {
        "call": "client.tenant.auth.refresh(refresh_token='...')",
        "scope": None,
        "auth": "none",
    },
    ("POST", "/v1/auth/setup-password"): {
        "call": "client.tenant.auth.setup_password(setup_token='...', password='...')",
        "scope": None,
        "auth": "none",
    },
    ("POST", "/v1/auth/recover-password"): {
        "call": "client.tenant.auth.recover_password(email='admin@acme.com')",
        "scope": None,
        "auth": "none",
    },
    ("GET", "/v1/meta"): {
        "call": "client.meta()",
        "scope": None,
        "auth": "none",
    },
    ("GET", "/v1/plans"): {
        "call": "client.plans()",
        "scope": None,
        "auth": "none",
    },
}

endpoints_list = []

for path, methods in spec["paths"].items():
    for method, op in methods.items():
        if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            continue
        m = method.upper()
        tags = op.get("tags", ["general"])
        primary_tag = tags[0] if tags else "general"
        group_id = TAG_TO_GROUP.get(primary_tag, "management")
        summary = op.get("summary") or op.get("operationId") or f"{m} {path}"
        desc = op.get("description") or summary

        meta = SDK_MAPPING.get((m, path), {})
        auth_type = meta.get("auth", "bearer" if "/platform/" in path or "/tenant/users" in path else "apiKey")
        scope = meta.get("scope", get_scope_from_op(op))
        sdk_call = meta.get("call")

        # Parse parameters
        params = []
        for p in op.get("parameters", []):
            p_schema = p.get("schema", {})
            params.append({
                "name": p["name"],
                "in": p["in"],
                "required": p.get("required", False),
                "type": p_schema.get("type", "string"),
                "description": p.get("description", ""),
                "example": str(p.get("example", "")),
            })

        # Request body
        request_body = None
        if "requestBody" in op:
            rb = op["requestBody"]
            content = rb.get("content", {})
            for c_type, c_val in content.items():
                b_schema = c_val.get("schema", {})
                ex = simplify_schema(b_schema)
                request_body = {
                    "required": rb.get("required", False),
                    "contentType": c_type,
                    "schemaSummary": b_schema.get("title", "Request Payload"),
                    "exampleJson": json.dumps(ex, indent=2),
                }
                break

        # Responses
        responses = []
        for status_code, resp_val in op.get("responses", {}).items():
            r_content = resp_val.get("content", {})
            ex_json = None
            if "application/json" in r_content:
                r_schema = r_content["application/json"].get("schema", {})
                ex_json = json.dumps(simplify_schema(r_schema), indent=2)
            responses.append({
                "status": int(status_code) if status_code.isdigit() else 200,
                "description": resp_val.get("description", ""),
                "exampleJson": ex_json,
            })

        # Generate sample cURL
        auth_header = ""
        if auth_type == "apiKey":
            auth_header = '  -H "Authorization: ApiKey <YOUR_API_KEY>" \\\n'
        elif auth_type == "bearer":
            auth_header = '  -H "Authorization: Bearer <ACCESS_TOKEN>" \\\n'
        elif auth_type == "operator":
            auth_header = '  -H "Authorization: Bearer <PLATFORM_ADMIN_TOKEN>" \\\n'

        curl_cmd = f'curl -X {m} "https://api.graphrec.io{path}" \\\n'
        if auth_header:
            curl_cmd += auth_header
        curl_cmd += '  -H "Accept: application/json"'
        if request_body:
            curl_cmd += ' \\\n  -H "Content-Type: application/json" \\\n'
            # single line or pretty json
            compact_json = json.dumps(json.loads(request_body["exampleJson"])).replace('"', '\\"')
            curl_cmd += f'  -d "{compact_json}"'

        # Generate JS fetch
        js_cmd = f"const response = await fetch('https://api.graphrec.io{path}', {{\n"
        js_cmd += f"  method: '{m}',\n"
        js_cmd += "  headers: {\n"
        js_cmd += "    'Accept': 'application/json',\n"
        if auth_type == "apiKey":
            js_cmd += "    'Authorization': 'ApiKey ' + apiKey,\n"
        elif auth_type in ("bearer", "operator"):
            js_cmd += "    'Authorization': 'Bearer ' + token,\n"
        if request_body:
            js_cmd += "    'Content-Type': 'application/json',\n"
        js_cmd += "  },\n"
        if request_body:
            js_cmd += f"  body: JSON.stringify({request_body['exampleJson']}),\n"
        js_cmd += "});\nconst data = await response.json();"

        # Python SDK sample
        if sdk_call:
            py_cmd = f"from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = {sdk_call}\nprint(result)"
        else:
            py_cmd = f"# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: {m} {path}"

        endpoint_id = f"{m.lower()}-{re.sub(r'[^a-zA-Z0-9]+', '-', path).strip('-')}"

        endpoints_list.append({
            "id": endpoint_id,
            "group": group_id,
            "method": m,
            "path": path,
            "summary": summary,
            "description": desc,
            "scope": scope,
            "auth": auth_type,
            "parameters": params,
            "requestBody": request_body,
            "responses": responses,
            "sdkMethod": sdk_call,
            "examples": {
                "curl": curl_cmd,
                "python": py_cmd,
                "javascript": js_cmd,
            },
        })

# Add unversioned system endpoints
endpoints_list.append({
    "id": "get-healthz",
    "group": "serving",
    "method": "GET",
    "path": "/healthz",
    "summary": "Liveness Probe",
    "description": "Liveness check that confirms the HTTP server process is running and can query PostgreSQL.",
    "scope": None,
    "auth": "none",
    "parameters": [],
    "responses": [{"status": 200, "description": "System live", "exampleJson": json.dumps({"status": "ok"}, indent=2)}],
    "sdkMethod": "client.health()",
    "examples": {
        "curl": "curl -X GET \"https://api.graphrec.io/healthz\" -H \"Accept: application/json\"",
        "python": "import urllib.request\nprint(urllib.request.urlopen('https://api.graphrec.io/healthz').read().decode())",
        "javascript": "const res = await fetch('https://api.graphrec.io/healthz');\nconst status = await res.json();",
    },
})

endpoints_list.append({
    "id": "get-readyz",
    "group": "serving",
    "method": "GET",
    "path": "/readyz",
    "summary": "Deep Readiness Probe",
    "description": "Deep readiness inspection measuring PostgreSQL, Redis, and Qdrant vector store dependencies.",
    "scope": None,
    "auth": "none",
    "parameters": [],
    "responses": [{
        "status": 200,
        "description": "System ready",
        "exampleJson": json.dumps({
            "status": "ready",
            "version": "1.1.0",
            "checks": {
                "database": {"status": "ok", "latency_ms": 1.2},
                "redis": {"status": "ok", "latency_ms": 0.8},
                "vector_store": {"status": "ok", "latency_ms": 2.1}
            }
        }, indent=2)
    }],
    "sdkMethod": "client.ready()",
    "examples": {
        "curl": "curl -X GET \"https://api.graphrec.io/readyz\" -H \"Accept: application/json\"",
        "python": "import urllib.request\nprint(urllib.request.urlopen('https://api.graphrec.io/readyz').read().decode())",
        "javascript": "const res = await fetch('https://api.graphrec.io/readyz');\nconst readiness = await res.json();",
    },
})

print(f"Generated {len(endpoints_list)} endpoints across {len(GROUPS)} groups.")

# Python SDK methods documentation
SDK_METHODS = [
    {
        "name": "recommendations.get",
        "namespace": "client.storefront",
        "signature": "client.storefront.recommendations.get(user_id: Optional[str] = None, top_n: int = 10, context: Optional[dict] = None, exclude_product_ids: Optional[list] = None, fallback_allowed: bool = True) -> Recommendations",
        "description": "Fetches real-time personalized recommendations for a known customer using their recent sequential history and trained user vector.",
        "parameters": [
            {"name": "user_id", "type": "str", "required": False, "description": "Shopper external ID. If omitted, falls back to popular items or session context."},
            {"name": "top_n", "type": "int", "required": False, "default": "10", "description": "Number of items to return (1-100)."},
            {"name": "context", "type": "dict", "required": False, "description": "Surface context, e.g. {'surface': 'cart', 'category': 'Shoes'}."},
            {"name": "exclude_product_ids", "type": "list[str]", "required": False, "description": "Product IDs to exclude from the recommendation shelf."},
            {"name": "fallback_allowed", "type": "bool", "required": False, "default": "True", "description": "Whether to return popular fallback if personalized inference is unavailable."},
        ],
        "returns": "Recommendations (items: list[RecommendationItem], model_version_id: str, strategy: str, fallback_used: bool)",
        "raises": ["AuthenticationError", "InputValidationError", "QuotaExceededError", "RateLimitError"],
        "example": "recs = client.storefront.recommendations.get(\n    user_id='customer-42',\n    top_n=10,\n    context={'surface': 'home'}\n)\nfor item in recs.items:\n    print(f'#{item.position}: {item.external_product_id}')",
    },
    {
        "name": "recommendations.for_session",
        "namespace": "client.storefront",
        "signature": "client.storefront.recommendations.for_session(item_ids: Sequence[str], top_n: int = 10, context: Optional[dict] = None) -> Recommendations",
        "description": "Generates session-based sequence recommendations for anonymous visitors using recent in-session item interactions and the global mean user vector.",
        "parameters": [
            {"name": "item_ids", "type": "Sequence[str]", "required": True, "description": "Ordered sequence of product external IDs interacted with during the session (up to 20)."},
            {"name": "top_n", "type": "int", "required": False, "default": "10", "description": "Number of items to return."},
            {"name": "context", "type": "dict", "required": False, "description": "Surface context dictionary."},
        ],
        "returns": "Recommendations object with strategy='session'.",
        "raises": ["AuthenticationError", "InputValidationError", "RateLimitError"],
        "example": "recs = client.storefront.recommendations.for_session(\n    item_ids=['SKU-101', 'SKU-205'],\n    top_n=8\n)",
    },
    {
        "name": "feedback.impression",
        "namespace": "client.storefront",
        "signature": "client.storefront.feedback.impression(recommendation: Union[Recommendations, str], items: Sequence[str]) -> FeedbackReceipt",
        "description": "Records recommendation shelf impressions to measure CTR and close the attribution loop.",
        "parameters": [
            {"name": "recommendation", "type": "Union[Recommendations, str]", "required": True, "description": "Recommendations instance or request_id UUID."},
            {"name": "items", "type": "Sequence[str]", "required": True, "description": "Product IDs displayed on screen to the customer."},
        ],
        "returns": "FeedbackReceipt (accepted: bool, feedback_id: str)",
        "raises": ["AuthenticationError", "NotFoundError"],
        "example": "client.storefront.feedback.impression(\n    recommendation=recs.request_id,\n    items=[item.external_product_id for item in recs.items]\n)",
    },
    {
        "name": "feedback.click",
        "namespace": "client.storefront",
        "signature": "client.storefront.feedback.click(recommendation: Union[Recommendations, str], item: str, position: int) -> FeedbackReceipt",
        "description": "Attributes a customer click to a previously served recommendation request.",
        "parameters": [
            {"name": "recommendation", "type": "Union[Recommendations, str]", "required": True, "description": "Request ID of the recommendation result."},
            {"name": "item", "type": "str", "required": True, "description": "External ID of the clicked product."},
            {"name": "position", "type": "int", "required": True, "description": "Rank position where the item appeared (1-indexed)."},
        ],
        "returns": "FeedbackReceipt",
        "raises": ["AuthenticationError", "NotFoundError"],
        "example": "client.storefront.feedback.click(\n    recommendation='5b1f0c9e-...',\n    item='SKU-100',\n    position=1\n)",
    },
    {
        "name": "feedback.conversion",
        "namespace": "client.storefront",
        "signature": "client.storefront.feedback.conversion(recommendation: Union[Recommendations, str], item: str, value: float = 0.0) -> FeedbackReceipt",
        "description": "Attributes a product purchase conversion to the recommendation that influenced it.",
        "parameters": [
            {"name": "recommendation", "type": "Union[Recommendations, str]", "required": True, "description": "Request ID of the recommendation."},
            {"name": "item", "type": "str", "required": True, "description": "Purchased product external ID."},
            {"name": "value", "type": "float", "required": False, "default": "0.0", "description": "Monetary value of the conversion in store currency."},
        ],
        "returns": "FeedbackReceipt",
        "raises": ["AuthenticationError", "NotFoundError"],
        "example": "client.storefront.feedback.conversion(\n    recommendation='5b1f0c9e-...',\n    item='SKU-100',\n    value=49.90\n)",
    },
    {
        "name": "events.create",
        "namespace": "client.storefront",
        "signature": "client.storefront.events.create(event_type: str, user_id: str, external_product_id: str, occurred_at: Optional[datetime] = None, event_id: Optional[str] = None, metadata: Optional[dict] = None, rating_value: Optional[float] = None) -> EventReceipt",
        "description": "Records an individual customer interaction event with idempotent deduplication.",
        "parameters": [
            {"name": "event_type", "type": "str", "required": True, "description": "One of: 'view', 'click', 'add_to_cart', 'purchase', 'rating', 'add_to_wishlist'."},
            {"name": "user_id", "type": "str", "required": True, "description": "Shopper external identifier."},
            {"name": "external_product_id", "type": "str", "required": True, "description": "Catalog product identifier."},
            {"name": "occurred_at", "type": "datetime", "required": False, "description": "Timestamp when the event occurred in UTC. Defaults to server now."},
            {"name": "event_id", "type": "str", "required": False, "description": "Unique client-generated idempotency key."},
        ],
        "returns": "EventReceipt (accepted: bool, duplicate: bool, event_id: str)",
        "raises": ["AuthenticationError", "QuotaExceededError", "RateLimitError"],
        "example": "client.storefront.events.create(\n    event_type='purchase',\n    user_id='customer-42',\n    external_product_id='SKU-100',\n    metadata={'order_id': 'ORD-991'}\n)",
    },
    {
        "name": "catalog.bulk_upsert",
        "namespace": "client.tenant",
        "signature": "client.tenant.catalog.bulk_upsert(products: Sequence[dict], request_id: Optional[str] = None) -> BulkUpsertResult",
        "description": "Bulk imports up to 1,000 product records per batch. Automatic deduplication and conflict resolution.",
        "parameters": [
            {"name": "products", "type": "Sequence[dict]", "required": True, "description": "List of product objects with external_id, title, price, category."},
            {"name": "request_id", "type": "str", "required": False, "description": "Idempotent batch request identifier."},
        ],
        "returns": "BulkUpsertResult (sync_id: str, total_received: int, upserted: int, errors: list)",
        "raises": ["AuthenticationError", "PayloadTooLargeError", "QuotaExceededError"],
        "example": "result = client.tenant.catalog.bulk_upsert([\n    {'external_id': 'SKU-1', 'title': 'Navy Blazer', 'price': '129.00', 'category': 'Suits'},\n    {'external_id': 'SKU-2', 'title': 'Silk Tie', 'price': '34.00', 'category': 'Accessories'}\n])\nprint(f'Upserted {result.upserted} items')",
    },
    {
        "name": "CatalogSync.run",
        "namespace": "graphrec_sdk.ecommerce",
        "signature": "CatalogSync(client: GraphRec, chunk_size: int = 250).run(items: Iterable[dict]) -> SyncSummary",
        "description": "High-level catalog ingestion helper that chunks large inventories to stay under the 16 KiB body limit, retrying transient errors automatically.",
        "parameters": [
            {"name": "items", "type": "Iterable[dict]", "required": True, "description": "Complete product inventory iterable."},
            {"name": "chunk_size", "type": "int", "required": False, "default": "250", "description": "Number of items per batch upsert call."},
        ],
        "returns": "SyncSummary (total_items: int, batches_sent: int, duration_seconds: float)",
        "raises": ["AuthenticationError", "RateLimitError"],
        "example": "from graphrec_sdk.ecommerce import CatalogSync\n\nsync = CatalogSync(client)\nsummary = sync.run(products_generator)\nprint(f'Synced {summary.total_items} products')",
    },
    {
        "name": "EventTracker",
        "namespace": "graphrec_sdk.ecommerce",
        "signature": "EventTracker(client: GraphRec, batch_size: int = 100, flush_interval: float = 5.0)",
        "description": "Thread-safe context manager that buffers interaction events in memory and flushes them to the batch endpoint periodically or upon exiting.",
        "parameters": [
            {"name": "batch_size", "type": "int", "required": False, "default": "100", "description": "Max events to buffer before triggering an automated flush."},
            {"name": "flush_interval", "type": "float", "required": False, "default": "5.0", "description": "Max seconds to wait before flushing pending events."},
        ],
        "returns": "Context manager yielding EventTracker instance with .view(), .cart(), .purchase() methods.",
        "raises": ["AuthenticationError"],
        "example": "from graphrec_sdk.ecommerce import EventTracker\n\nwith EventTracker(client, batch_size=50) as tracker:\n    tracker.view('cus-99', 'SKU-100')\n    tracker.add_to_cart('cus-99', 'SKU-100', quantity=1)\n    tracker.purchase('cus-99', 'SKU-100', order_id='ORD-1')",
    },
]

# Write out docsData.ts
ts_content = f"""// AUTO-GENERATED from openapi.json and graphrec_sdk routes. Do not edit manually.
export interface EndpointDoc {{
  id: string;
  group: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  summary: string;
  description: string;
  scope?: string | null;
  auth: "none" | "apiKey" | "bearer" | "operator";
  parameters: Array<{{
    name: string;
    in: "path" | "query" | "header";
    required: boolean;
    type: string;
    description: string;
    example?: string;
  }}>;
  requestBody?: {{
    required: boolean;
    contentType: string;
    schemaSummary: string;
    exampleJson: string;
  }} | null;
  responses: Array<{{
    status: number;
    description: string;
    exampleJson?: string | null;
  }}>;
  sdkMethod?: string | null;
  examples: {{
    curl: string;
    python: string;
    javascript: string;
  }};
}}

export interface SdkMethodDoc {{
  name: string;
  namespace: string;
  signature: string;
  description: string;
  parameters: Array<{{ name: string; type: string; required: boolean; description: string; default?: string }}>;
  returns: string;
  raises: string[];
  example: string;
}}

export interface NavGroup {{
  id: string;
  title: string;
  description: string;
}}

export const DOCS_GROUPS: NavGroup[] = {json.dumps(GROUPS, indent=2)};

export const ENDPOINTS: EndpointDoc[] = {json.dumps(endpoints_list, indent=2)};

export const SDK_METHODS: SdkMethodDoc[] = {json.dumps(SDK_METHODS, indent=2)};

export const ERROR_CODES = [
  {{ code: "malformed_request", status: 400, meaning: "Request validation failed or Content-Type header is not application/json", retryable: false }},
  {{ code: "authentication_failed", status: 401, meaning: "API key or Bearer token is missing, expired, revoked or invalid", retryable: false }},
  {{ code: "insufficient_scope", status: 403, meaning: "Credential is valid but lacks the required permission scope (e.g. catalog:write)", retryable: false }},
  {{ code: "tenant_inactive", status: 403, meaning: "Tenant workspace is suspended or archived. Only status probes are admitted", retryable: false }},
  {{ code: "resource_not_found", status: 404, meaning: "Resource ID does not exist within the caller's tenant boundary", retryable: false }},
  {{ code: "duplicate_resource", status: 409, meaning: "Resource with that ID, version tag or unique constraint already exists", retryable: false }},
  {{ code: "payload_too_large", status: 413, meaning: "Request body exceeded max permitted size (16 KiB default / 50 MiB multipart)", retryable: false }},
  {{ code: "rate_limit_exceeded", status: 429, meaning: "Sliding-window request quota exhausted. Retry-After header indicates wait duration", retryable: true }},
  {{ code: "service_unavailable", status: 503, meaning: "A backend dependency (Postgres or ML model host) is temporarily degraded", retryable: true }},
  {{ code: "recommendation_unavailable", status: 503, meaning: "Model is not serving and fallback_allowed was explicitly set to false", retryable: true }},
];

export const PLAN_LIMITS = [
  {{ dimension: "stored_products", free: "5,000", pro: "50,000", enterprise: "Custom", unit: "SKUs" }},
  {{ dimension: "accepted_events", free: "50,000 / mo", pro: "500,000 / mo", enterprise: "Custom", unit: "events" }},
  {{ dimension: "recommendation_requests", free: "10,000 / mo", pro: "250,000 / mo", enterprise: "Custom", unit: "queries" }},
  {{ dimension: "model_training_jobs", free: "3 / mo", pro: "20 / mo", enterprise: "Unlimited", unit: "runs" }},
  {{ dimension: "api_keys", free: "2 keys", pro: "10 keys", enterprise: "Unlimited", unit: "keys" }},
];
"""

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(ts_content)

print(f"Wrote docs data to {OUTPUT_PATH}")
