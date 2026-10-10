#!/usr/bin/env python3
"""Builds web/src/docs/docsData.ts from openapi.json and SDK route specifications."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

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

# Write out docsData.ts
ts_content = f"""// AUTO-GENERATED from openapi.json (SDK reference: sdkData.ts). Do not edit manually.
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

export interface NavGroup {{
  id: string;
  title: string;
  description: string;
  tags?: string[];
}}

export const DOCS_GROUPS: NavGroup[] = {json.dumps(GROUPS, indent=2)};

export const ENDPOINTS: EndpointDoc[] = {json.dumps(endpoints_list, indent=2)};

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
