// AUTO-GENERATED from openapi.json and graphrec_sdk routes. Do not edit manually.
export interface EndpointDoc {
  id: string;
  group: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  summary: string;
  description: string;
  scope?: string | null;
  auth: "none" | "apiKey" | "bearer" | "operator";
  parameters: Array<{
    name: string;
    in: "path" | "query" | "header";
    required: boolean;
    type: string;
    description: string;
    example?: string;
  }>;
  requestBody?: {
    required: boolean;
    contentType: string;
    schemaSummary: string;
    exampleJson: string;
  } | null;
  responses: Array<{
    status: number;
    description: string;
    exampleJson?: string | null;
  }>;
  sdkMethod?: string | null;
  examples: {
    curl: string;
    python: string;
    javascript: string;
  };
}

export interface SdkMethodDoc {
  name: string;
  namespace: string;
  signature: string;
  description: string;
  parameters: Array<{ name: string; type: string; required: boolean; description: string; default?: string }>;
  returns: string;
  raises: string[];
  example: string;
}

export interface NavGroup {
  id: string;
  title: string;
  description: string;
  tags?: string[];
}

export const DOCS_GROUPS: NavGroup[] = [
  {
    "id": "recommendations",
    "title": "Recommendations & Feedback",
    "description": "Real-time personalization inference, session recommendations, and attribution telemetry.",
    "tags": [
      "recommendations"
    ]
  },
  {
    "id": "catalog",
    "title": "Catalog & Products",
    "description": "Product catalog synchronization, attribute indexing, and bulk upsert operations.",
    "tags": [
      "catalog"
    ]
  },
  {
    "id": "events",
    "title": "Events & Ingestion",
    "description": "Shopper interaction events, batch uploads, and idempotency tracking.",
    "tags": [
      "events"
    ]
  },
  {
    "id": "datasets",
    "title": "Datasets & Snapshots",
    "description": "Dataset file uploads and point-in-time training cohort snapshots.",
    "tags": [
      "datasets"
    ]
  },
  {
    "id": "models",
    "title": "Models & Training",
    "description": "Sequential DGSR training jobs, model version registry, and serving lifecycle.",
    "tags": [
      "models",
      "training"
    ]
  },
  {
    "id": "serving",
    "title": "Serving & Monitoring",
    "description": "Active deployment status, autoscaling health, latency histograms, and system probes.",
    "tags": [
      "deployment"
    ]
  },
  {
    "id": "management",
    "title": "Workspace & Management",
    "description": "API key credentials, member invitations, subscription limits, usage trends, and audit trail.",
    "tags": [
      "api-keys",
      "tenant-users",
      "subscription",
      "usage",
      "audit",
      "tenants"
    ]
  },
  {
    "id": "platform",
    "title": "Platform Operations",
    "description": "Cross-tenant administrative APIs for cluster operators.",
    "tags": [
      "platform"
    ]
  },
  {
    "id": "auth",
    "title": "Authentication & Accounts",
    "description": "Member authentication, password setup, recovery, and session token rotation.",
    "tags": [
      "authentication",
      "meta"
    ]
  }
];

export const ENDPOINTS: EndpointDoc[] = [
  {
    "id": "get-v1-api-keys",
    "group": "management",
    "method": "GET",
    "path": "/v1/api-keys",
    "summary": "List Api Keys",
    "description": "List Api Keys",
    "scope": "keys:write",
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"created_at\": \"...\",\n      \"expires_at\": \"...\",\n      \"grace_expires_at\": \"...\",\n      \"id\": \"...\",\n      \"last_used_at\": \"...\",\n      \"name\": \"...\",\n      \"prefix\": \"...\",\n      \"revoked_at\": \"...\",\n      \"scopes\": \"...\",\n      \"status\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.api_keys.list()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/api-keys\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.api_keys.list()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/api-keys', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-api-keys",
    "group": "management",
    "method": "POST",
    "path": "/v1/api-keys",
    "summary": "Create Api Key",
    "description": "Create Api Key",
    "scope": "keys:write",
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"expires_at\": {},\n  \"name\": \"example_string\",\n  \"scopes\": [\n    \"billing:read\"\n  ]\n}"
    },
    "responses": [
      {
        "status": 201,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"expires_at\": {},\n  \"grace_expires_at\": {},\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_used_at\": {},\n  \"name\": \"example_string\",\n  \"prefix\": \"example_string\",\n  \"revoked_at\": {},\n  \"scopes\": [\n    \"billing:read\"\n  ],\n  \"secret\": \"example_string\",\n  \"status\": \"active\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.api_keys.create(name='Storefront Key', scopes=['events:write', 'recommendations:read'])",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/api-keys\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"expires_at\\\": {}, \\\"name\\\": \\\"example_string\\\", \\\"scopes\\\": [\\\"billing:read\\\"]}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.api_keys.create(name='Storefront Key', scopes=['events:write', 'recommendations:read'])\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/api-keys', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"expires_at\": {},\n  \"name\": \"example_string\",\n  \"scopes\": [\n    \"billing:read\"\n  ]\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "delete-v1-api-keys-key-id",
    "group": "management",
    "method": "DELETE",
    "path": "/v1/api-keys/{key_id}",
    "summary": "Revoke Api Key",
    "description": "Revoke Api Key",
    "scope": "keys:write",
    "auth": "bearer",
    "parameters": [
      {
        "name": "key_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"expires_at\": {},\n  \"grace_expires_at\": {},\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_used_at\": {},\n  \"name\": \"example_string\",\n  \"prefix\": \"example_string\",\n  \"revoked_at\": {},\n  \"scopes\": [\n    \"billing:read\"\n  ],\n  \"status\": \"active\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.api_keys.revoke(key_id='key-123')",
    "examples": {
      "curl": "curl -X DELETE \"https://api.graphrec.io/v1/api-keys/{key_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.api_keys.revoke(key_id='key-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/api-keys/{key_id}', {\n  method: 'DELETE',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-api-keys-key-id",
    "group": "management",
    "method": "GET",
    "path": "/v1/api-keys/{key_id}",
    "summary": "Get Api Key",
    "description": "Get Api Key",
    "scope": "keys:write",
    "auth": "bearer",
    "parameters": [
      {
        "name": "key_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"expires_at\": {},\n  \"grace_expires_at\": {},\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_used_at\": {},\n  \"name\": \"example_string\",\n  \"prefix\": \"example_string\",\n  \"revoked_at\": {},\n  \"scopes\": [\n    \"billing:read\"\n  ],\n  \"status\": \"active\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.api_keys.get(key_id='key-123')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/api-keys/{key_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.api_keys.get(key_id='key-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/api-keys/{key_id}', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-api-keys-key-id-rotate",
    "group": "management",
    "method": "POST",
    "path": "/v1/api-keys/{key_id}/rotate",
    "summary": "Rotate Api Key",
    "description": "Rotate Api Key",
    "scope": "keys:write",
    "auth": "bearer",
    "parameters": [
      {
        "name": "key_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"grace_period_seconds\": 1,\n  \"reason\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"expires_at\": {},\n  \"grace_expires_at\": {},\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_used_at\": {},\n  \"name\": \"example_string\",\n  \"prefix\": \"example_string\",\n  \"revoked_at\": {},\n  \"scopes\": [\n    \"billing:read\"\n  ],\n  \"secret\": \"example_string\",\n  \"status\": \"active\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.api_keys.rotate(key_id='key-123')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/api-keys/{key_id}/rotate\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"grace_period_seconds\\\": 1, \\\"reason\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.api_keys.rotate(key_id='key-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/api-keys/{key_id}/rotate', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"grace_period_seconds\": 1,\n  \"reason\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-audit",
    "group": "management",
    "method": "GET",
    "path": "/v1/audit",
    "summary": "List Tenant Audit",
    "description": "List Tenant Audit",
    "scope": "audit:read",
    "auth": "bearer",
    "parameters": [
      {
        "name": "action",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "outcome",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "since",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "until",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "before",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "Keyset cursor from next_before.",
        "example": ""
      },
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "type": "integer",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"action_type\": \"...\",\n      \"actor_reference\": \"...\",\n      \"actor_type\": \"...\",\n      \"correlation_id\": \"...\",\n      \"id\": \"...\",\n      \"occurred_at\": \"...\",\n      \"outcome\": \"...\",\n      \"reason\": \"...\",\n      \"resource_reference\": \"...\",\n      \"resource_type\": \"...\"\n    }\n  ],\n  \"next_before\": {}\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.audit.list(limit=50)",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/audit\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.audit.list(limit=50)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/audit', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-auth-login",
    "group": "auth",
    "method": "POST",
    "path": "/v1/auth/login",
    "summary": "Login",
    "description": "Login",
    "scope": null,
    "auth": "none",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"email\": \"example_string\",\n  \"password\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"access_token\": \"example_string\",\n  \"email\": {},\n  \"expires_in\": 1,\n  \"refresh_token\": \"example_string\",\n  \"scopes\": [\n    \"example_string\"\n  ],\n  \"tenant_name\": {},\n  \"token_type\": \"example_string\",\n  \"user_role\": \"tenant_administrator\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.auth.login(email='admin@acme.com', password='...')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/auth/login\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"email\\\": \\\"example_string\\\", \\\"password\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.auth.login(email='admin@acme.com', password='...')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/auth/login', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"email\": \"example_string\",\n  \"password\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-auth-logout",
    "group": "auth",
    "method": "POST",
    "path": "/v1/auth/logout",
    "summary": "Logout",
    "description": "End the caller's sessions: every access token for this user stops working\nimmediately (auth epoch bump) and all refresh sessions are revoked.",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 204,
        "description": "Successful Response",
        "exampleJson": null
      }
    ],
    "sdkMethod": "client.tenant.auth.logout()",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/auth/logout\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.auth.logout()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/auth/logout', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-auth-recover-password",
    "group": "auth",
    "method": "POST",
    "path": "/v1/auth/recover-password",
    "summary": "Recover Password",
    "description": "Recover Password",
    "scope": null,
    "auth": "none",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"email\": {},\n  \"password\": \"example_string\",\n  \"recovery_token\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.auth.recover_password(email='admin@acme.com')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/auth/recover-password\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"email\\\": {}, \\\"password\\\": \\\"example_string\\\", \\\"recovery_token\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.auth.recover_password(email='admin@acme.com')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/auth/recover-password', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"email\": {},\n  \"password\": \"example_string\",\n  \"recovery_token\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-auth-refresh",
    "group": "auth",
    "method": "POST",
    "path": "/v1/auth/refresh",
    "summary": "Refresh Session",
    "description": "Exchange a refresh token for a new token pair (A-05).\n\nEach refresh token works once and is replaced by the one returned here. The\nsign-in's absolute lifetime is not extended. Presenting a token that was\nalready rotated signs the user out everywhere.",
    "scope": null,
    "auth": "none",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"refresh_token\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"access_token\": \"example_string\",\n  \"email\": {},\n  \"expires_in\": 1,\n  \"refresh_token\": \"example_string\",\n  \"scopes\": [\n    \"example_string\"\n  ],\n  \"tenant_name\": {},\n  \"token_type\": \"example_string\",\n  \"user_role\": \"tenant_administrator\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.auth.refresh(refresh_token='...')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/auth/refresh\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"refresh_token\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.auth.refresh(refresh_token='...')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/auth/refresh', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"refresh_token\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-auth-setup-password",
    "group": "auth",
    "method": "POST",
    "path": "/v1/auth/setup-password",
    "summary": "Setup Password",
    "description": "Setup Password",
    "scope": null,
    "auth": "none",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"email\": {},\n  \"password\": \"example_string\",\n  \"setup_token\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"access_token\": \"example_string\",\n  \"email\": {},\n  \"expires_in\": 1,\n  \"refresh_token\": \"example_string\",\n  \"scopes\": [\n    \"example_string\"\n  ],\n  \"tenant_name\": {},\n  \"token_type\": \"example_string\",\n  \"user_role\": \"tenant_administrator\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.auth.setup_password(setup_token='...', password='...')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/auth/setup-password\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"email\\\": {}, \\\"password\\\": \\\"example_string\\\", \\\"setup_token\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.auth.setup_password(setup_token='...', password='...')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/auth/setup-password', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"email\": {},\n  \"password\": \"example_string\",\n  \"setup_token\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-catalog-syncs",
    "group": "catalog",
    "method": "GET",
    "path": "/v1/catalog-syncs",
    "summary": "List Catalog Syncs",
    "description": "List Catalog Syncs",
    "scope": "catalog:read",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "[\n  {\n    \"accepted_count\": 1,\n    \"created_at\": \"2026-10-10T12:00:00Z\",\n    \"created_count\": 1,\n    \"failures\": [\n      \"...\"\n    ],\n    \"outcomes\": [\n      {}\n    ],\n    \"rejected_count\": 1,\n    \"request_id\": {},\n    \"skipped_count\": 1,\n    \"status\": \"example_string\",\n    \"sync_id\": {},\n    \"updated_count\": 1\n  }\n]"
      }
    ],
    "sdkMethod": "client.tenant.catalog.list_syncs(limit=20)",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/catalog-syncs\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.catalog.list_syncs(limit=20)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/catalog-syncs', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-catalog-syncs-sync-id",
    "group": "catalog",
    "method": "GET",
    "path": "/v1/catalog-syncs/{sync_id}",
    "summary": "Get Catalog Sync",
    "description": "Get Catalog Sync",
    "scope": "catalog:read",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "sync_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"accepted_count\": 1,\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"created_count\": 1,\n  \"failures\": [\n    {\n      \"external_id\": \"...\",\n      \"reason\": \"...\"\n    }\n  ],\n  \"outcomes\": [\n    {}\n  ],\n  \"rejected_count\": 1,\n  \"request_id\": {},\n  \"skipped_count\": 1,\n  \"status\": \"example_string\",\n  \"sync_id\": {},\n  \"updated_count\": 1\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.catalog.get_sync(sync_id='sync-123')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/catalog-syncs/{sync_id}\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.catalog.get_sync(sync_id='sync-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/catalog-syncs/{sync_id}', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-datasets-snapshots",
    "group": "datasets",
    "method": "GET",
    "path": "/v1/datasets/snapshots",
    "summary": "List Dataset Snapshots",
    "description": "List Dataset Snapshots",
    "scope": "training:read",
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"artifact_uri\": \"...\",\n      \"checksum\": \"...\",\n      \"created_at\": \"...\",\n      \"cutoff_at\": \"...\",\n      \"event_count\": \"...\",\n      \"id\": \"...\",\n      \"product_count\": \"...\",\n      \"tenant_id\": \"...\",\n      \"training_job_id\": \"...\",\n      \"user_count\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.datasets.list_snapshots()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/datasets/snapshots\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.datasets.list_snapshots()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/datasets/snapshots', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-datasets-snapshots",
    "group": "datasets",
    "method": "POST",
    "path": "/v1/datasets/snapshots",
    "summary": "Create Dataset Snapshot",
    "description": "Create Dataset Snapshot",
    "scope": "training:write",
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"cutoff_at\": {},\n  \"description\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"artifact_uri\": \"example_string\",\n  \"checksum\": \"example_string\",\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"cutoff_at\": \"2026-10-10T12:00:00Z\",\n  \"event_count\": 1,\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"product_count\": 1,\n  \"tenant_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"training_job_id\": {},\n  \"user_count\": 1\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.datasets.create_snapshot()",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/datasets/snapshots\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"cutoff_at\\\": {}, \\\"description\\\": {}}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.datasets.create_snapshot()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/datasets/snapshots', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"cutoff_at\": {},\n  \"description\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-datasets-snapshots-snapshot-id",
    "group": "datasets",
    "method": "GET",
    "path": "/v1/datasets/snapshots/{snapshot_id}",
    "summary": "Get Dataset Snapshot",
    "description": "Get Dataset Snapshot",
    "scope": "training:read",
    "auth": "bearer",
    "parameters": [
      {
        "name": "snapshot_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"artifact_uri\": \"example_string\",\n  \"checksum\": \"example_string\",\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"cutoff_at\": \"2026-10-10T12:00:00Z\",\n  \"event_count\": 1,\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"product_count\": 1,\n  \"tenant_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"training_job_id\": {},\n  \"user_count\": 1\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.datasets.get_snapshot(snapshot_id='snap-123')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/datasets/snapshots/{snapshot_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.datasets.get_snapshot(snapshot_id='snap-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/datasets/snapshots/{snapshot_id}', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-datasets-upload",
    "group": "datasets",
    "method": "POST",
    "path": "/v1/datasets/upload",
    "summary": "Upload Dataset File",
    "description": "Upload Dataset File",
    "scope": "catalog:write, events:write",
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "multipart/form-data",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"file\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"accepted_events\": 1,\n  \"accepted_products\": 1,\n  \"dataset_snapshot\": {\n    \"artifact_uri\": \"example_string\",\n    \"checksum\": \"example_string\",\n    \"created_at\": \"2026-10-10T12:00:00Z\",\n    \"cutoff_at\": \"2026-10-10T12:00:00Z\",\n    \"event_count\": 1,\n    \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n    \"product_count\": 1,\n    \"tenant_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n    \"training_job_id\": {},\n    \"user_count\": 1\n  }\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.datasets.upload(file=open('catalog.csv', 'rb'))",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/datasets/upload\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"file\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.datasets.upload(file=open('catalog.csv', 'rb'))\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/datasets/upload', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"file\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-deployment",
    "group": "serving",
    "method": "GET",
    "path": "/v1/deployment",
    "summary": "Get Deployment Status",
    "description": "Get Deployment Status",
    "scope": "deployments:read",
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"active_model_version_id\": {},\n  \"desired_capacity\": 1,\n  \"desired_model_version_id\": {},\n  \"failure_reason\": {},\n  \"id\": {},\n  \"last_transition_at\": {},\n  \"rate_limiter\": {},\n  \"ready_capacity\": 1,\n  \"status\": \"example_string\"\n}"
      }
    ],
    "sdkMethod": "client.tenant.deployment.get()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/deployment\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.deployment.get()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/deployment', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-deployment-scaling",
    "group": "serving",
    "method": "GET",
    "path": "/v1/deployment/scaling",
    "summary": "Get Scaling Status",
    "description": "XR-F-08: the tenant's capacity policy, live demand and recent scaling events.",
    "scope": "deployments:read",
    "auth": "bearer",
    "parameters": [
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "type": "integer",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"desired_capacity\": 1,\n  \"events\": [\n    {\n      \"from_capacity\": \"...\",\n      \"id\": \"...\",\n      \"max_capacity\": \"...\",\n      \"measured_rpm\": \"...\",\n      \"model_version_id\": \"...\",\n      \"occurred_at\": \"...\",\n      \"peak_rpm\": \"...\",\n      \"reason\": \"...\",\n      \"to_capacity\": \"...\"\n    }\n  ],\n  \"last_scaled_at\": {},\n  \"limitation\": \"example_string\",\n  \"managed\": true,\n  \"max_capacity\": 1,\n  \"measured_rpm\": 1,\n  \"min_capacity\": 1,\n  \"peak_rpm\": 1,\n  \"ready_capacity\": 1,\n  \"scale_down_stabilization_seconds\": 1,\n  \"serving_slots\": {}\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.deployment.scaling()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/deployment/scaling\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.deployment.scaling()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/deployment/scaling', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-events",
    "group": "events",
    "method": "GET",
    "path": "/v1/events",
    "summary": "List Events",
    "description": "Recently received events, newest first, including single submissions.",
    "scope": "events:read",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "type": "integer",
        "description": "",
        "example": ""
      },
      {
        "name": "user_id",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "event_type",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "external_product_id",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "[\n  {\n    \"context\": {},\n    \"created_at\": \"2026-10-10T12:00:00Z\",\n    \"event_id\": \"example_string\",\n    \"event_type\": \"example_string\",\n    \"external_product_id\": {},\n    \"occurred_at\": \"2026-10-10T12:00:00Z\",\n    \"user_id\": {}\n  }\n]"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.storefront.events.list(user_id='cus-9931', limit=50)",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/events\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.events.list(user_id='cus-9931', limit=50)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/events', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-events",
    "group": "events",
    "method": "POST",
    "path": "/v1/events",
    "summary": "Submit Event",
    "description": "Submit Event",
    "scope": "events:write",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"context\": {},\n  \"event_id\": \"example_string\",\n  \"event_type\": \"view\",\n  \"external_product_id\": {},\n  \"occurred_at\": \"2026-10-10T12:00:00Z\",\n  \"user_id\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"accepted\": true,\n  \"duplicate\": true,\n  \"event_id\": \"example_string\",\n  \"received_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.storefront.events.create(event_type='view', user_id='cus-9931', external_product_id='SKU-100')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/events\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"context\\\": {}, \\\"event_id\\\": \\\"example_string\\\", \\\"event_type\\\": \\\"view\\\", \\\"external_product_id\\\": {}, \\\"occurred_at\\\": \\\"2026-10-10T12:00:00Z\\\", \\\"user_id\\\": {}}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.events.create(event_type='view', user_id='cus-9931', external_product_id='SKU-100')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/events', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"context\": {},\n  \"event_id\": \"example_string\",\n  \"event_type\": \"view\",\n  \"external_product_id\": {},\n  \"occurred_at\": \"2026-10-10T12:00:00Z\",\n  \"user_id\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-events-batches",
    "group": "events",
    "method": "GET",
    "path": "/v1/events/batches",
    "summary": "List Event Batches",
    "description": "List Event Batches",
    "scope": "events:read",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "[\n  {\n    \"accepted_count\": 1,\n    \"created_at\": \"2026-10-10T12:00:00Z\",\n    \"duplicate_count\": 1,\n    \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n    \"outcomes\": [\n      \"...\"\n    ],\n    \"rejected_count\": 1,\n    \"request_id\": {},\n    \"status\": \"example_string\"\n  }\n]"
      }
    ],
    "sdkMethod": "client.storefront.events.list_batches(limit=20)",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/events/batches\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.events.list_batches(limit=20)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/events/batches', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-events-batches",
    "group": "events",
    "method": "POST",
    "path": "/v1/events/batches",
    "summary": "Submit Event Batch",
    "description": "Submit Event Batch",
    "scope": "events:write",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"events\": [\n    {\n      \"context\": \"...\",\n      \"event_id\": \"...\",\n      \"event_type\": \"...\",\n      \"external_product_id\": \"...\",\n      \"occurred_at\": \"...\",\n      \"user_id\": \"...\"\n    }\n  ],\n  \"request_id\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"accepted_count\": 1,\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"duplicate_count\": 1,\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"outcomes\": [\n    {\n      \"event_id\": \"...\",\n      \"reason\": \"...\",\n      \"status\": \"...\"\n    }\n  ],\n  \"rejected_count\": 1,\n  \"request_id\": {},\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.storefront.events.create_batch(events=[{'event_type': 'view', 'user_id': 'cus-9931', 'external_product_id': 'SKU-100'}])",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/events/batches\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"events\\\": [{\\\"context\\\": \\\"...\\\", \\\"event_id\\\": \\\"...\\\", \\\"event_type\\\": \\\"...\\\", \\\"external_product_id\\\": \\\"...\\\", \\\"occurred_at\\\": \\\"...\\\", \\\"user_id\\\": \\\"...\\\"}], \\\"request_id\\\": {}}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.events.create_batch(events=[{'event_type': 'view', 'user_id': 'cus-9931', 'external_product_id': 'SKU-100'}])\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/events/batches', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"events\": [\n    {\n      \"context\": \"...\",\n      \"event_id\": \"...\",\n      \"event_type\": \"...\",\n      \"external_product_id\": \"...\",\n      \"occurred_at\": \"...\",\n      \"user_id\": \"...\"\n    }\n  ],\n  \"request_id\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-events-batches-batch-id",
    "group": "events",
    "method": "GET",
    "path": "/v1/events/batches/{batch_id}",
    "summary": "Get Event Batch",
    "description": "Get Event Batch",
    "scope": "events:read",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "batch_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"accepted_count\": 1,\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"duplicate_count\": 1,\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"outcomes\": [\n    {\n      \"event_id\": \"...\",\n      \"reason\": \"...\",\n      \"status\": \"...\"\n    }\n  ],\n  \"rejected_count\": 1,\n  \"request_id\": {},\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.storefront.events.get_batch(batch_id='batch-123')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/events/batches/{batch_id}\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.events.get_batch(batch_id='batch-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/events/batches/{batch_id}', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-feedback-clicks",
    "group": "recommendations",
    "method": "POST",
    "path": "/v1/feedback/clicks",
    "summary": "Submit Click Feedback",
    "description": "Submit Click Feedback",
    "scope": "events:write",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"context\": {},\n  \"event_id\": \"example_string\",\n  \"external_product_id\": \"example_string\",\n  \"impression_event_id\": {},\n  \"occurred_at\": \"2026-10-10T12:00:00Z\",\n  \"position\": 1,\n  \"request_id\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"accepted\": true,\n  \"duplicate\": true,\n  \"event_id\": \"example_string\",\n  \"feedback_type\": \"example_string\",\n  \"received_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.storefront.feedback.click(recommendation='5b1f0c9e-...', item='SKU-100', position=1)",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/feedback/clicks\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"context\\\": {}, \\\"event_id\\\": \\\"example_string\\\", \\\"external_product_id\\\": \\\"example_string\\\", \\\"impression_event_id\\\": {}, \\\"occurred_at\\\": \\\"2026-10-10T12:00:00Z\\\", \\\"position\\\": 1, \\\"request_id\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.feedback.click(recommendation='5b1f0c9e-...', item='SKU-100', position=1)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/feedback/clicks', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"context\": {},\n  \"event_id\": \"example_string\",\n  \"external_product_id\": \"example_string\",\n  \"impression_event_id\": {},\n  \"occurred_at\": \"2026-10-10T12:00:00Z\",\n  \"position\": 1,\n  \"request_id\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-feedback-conversions",
    "group": "recommendations",
    "method": "POST",
    "path": "/v1/feedback/conversions",
    "summary": "Submit Conversion Feedback",
    "description": "Submit Conversion Feedback",
    "scope": "events:write",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"context\": {},\n  \"event_id\": \"example_string\",\n  \"external_product_id\": \"example_string\",\n  \"occurred_at\": \"2026-10-10T12:00:00Z\",\n  \"position\": {},\n  \"request_id\": \"example_string\",\n  \"value\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"accepted\": true,\n  \"duplicate\": true,\n  \"event_id\": \"example_string\",\n  \"feedback_type\": \"example_string\",\n  \"received_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.storefront.feedback.conversion(recommendation='5b1f0c9e-...', item='SKU-100', value=49.99)",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/feedback/conversions\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"context\\\": {}, \\\"event_id\\\": \\\"example_string\\\", \\\"external_product_id\\\": \\\"example_string\\\", \\\"occurred_at\\\": \\\"2026-10-10T12:00:00Z\\\", \\\"position\\\": {}, \\\"request_id\\\": \\\"example_string\\\", \\\"value\\\": {}}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.feedback.conversion(recommendation='5b1f0c9e-...', item='SKU-100', value=49.99)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/feedback/conversions', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"context\": {},\n  \"event_id\": \"example_string\",\n  \"external_product_id\": \"example_string\",\n  \"occurred_at\": \"2026-10-10T12:00:00Z\",\n  \"position\": {},\n  \"request_id\": \"example_string\",\n  \"value\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-feedback-impressions",
    "group": "recommendations",
    "method": "POST",
    "path": "/v1/feedback/impressions",
    "summary": "Submit Impression Feedback",
    "description": "Submit Impression Feedback",
    "scope": "events:write",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"context\": {},\n  \"event_id\": \"example_string\",\n  \"items\": [\n    {\n      \"external_product_id\": \"...\",\n      \"position\": \"...\"\n    }\n  ],\n  \"occurred_at\": \"2026-10-10T12:00:00Z\",\n  \"request_id\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"accepted\": true,\n  \"duplicate\": true,\n  \"event_id\": \"example_string\",\n  \"feedback_type\": \"example_string\",\n  \"received_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.storefront.feedback.impression(recommendation='5b1f0c9e-...', items=['SKU-100', 'SKU-200'])",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/feedback/impressions\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"context\\\": {}, \\\"event_id\\\": \\\"example_string\\\", \\\"items\\\": [{\\\"external_product_id\\\": \\\"...\\\", \\\"position\\\": \\\"...\\\"}], \\\"occurred_at\\\": \\\"2026-10-10T12:00:00Z\\\", \\\"request_id\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.feedback.impression(recommendation='5b1f0c9e-...', items=['SKU-100', 'SKU-200'])\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/feedback/impressions', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"context\": {},\n  \"event_id\": \"example_string\",\n  \"items\": [\n    {\n      \"external_product_id\": \"...\",\n      \"position\": \"...\"\n    }\n  ],\n  \"occurred_at\": \"2026-10-10T12:00:00Z\",\n  \"request_id\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-meta",
    "group": "auth",
    "method": "GET",
    "path": "/v1/meta",
    "summary": "Get Meta",
    "description": "Get Meta",
    "scope": null,
    "auth": "none",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"environment\": \"example_string\",\n  \"features\": {\n    \"development_placeholders\": true\n  },\n  \"product\": \"example_string\",\n  \"version\": \"example_string\"\n}"
      }
    ],
    "sdkMethod": "client.meta()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/meta\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.meta()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/meta', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-metrics-summary",
    "group": "serving",
    "method": "GET",
    "path": "/v1/metrics/summary",
    "summary": "Get Metrics Summary",
    "description": "Get Metrics Summary",
    "scope": "metrics:read",
    "auth": "bearer",
    "parameters": [
      {
        "name": "window_minutes",
        "in": "query",
        "required": false,
        "type": "integer",
        "description": "Width of the measurement window ending now.",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"active_model_version_id\": {},\n  \"error_rate\": {},\n  \"fallback_rate\": {},\n  \"p95_latency_ms\": {},\n  \"quality\": {},\n  \"request_count\": 1,\n  \"request_rate\": 1,\n  \"window_end\": \"2026-10-10T12:00:00Z\",\n  \"window_start\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.metrics.summary(window_minutes=1440)",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/metrics/summary\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.metrics.summary(window_minutes=1440)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/metrics/summary', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-model-versions",
    "group": "models",
    "method": "GET",
    "path": "/v1/model-versions",
    "summary": "List Model Versions",
    "description": "List Model Versions",
    "scope": "models:read",
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"activated_at\": \"...\",\n      \"artifact_uri\": \"...\",\n      \"created_at\": \"...\",\n      \"id\": \"...\",\n      \"metrics\": \"...\",\n      \"model_type\": \"...\",\n      \"qdrant_collection\": \"...\",\n      \"status\": \"...\",\n      \"version_tag\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.model_versions.list()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/model-versions\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.model_versions.list()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/model-versions', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-model-versions",
    "group": "models",
    "method": "POST",
    "path": "/v1/model-versions",
    "summary": "Register Model Version",
    "description": "Register Model Version",
    "scope": "models:write",
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"artifact_uri\": {},\n  \"metrics\": {},\n  \"model_type\": \"example_string\",\n  \"version_tag\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"activated_at\": {},\n  \"artifact_uri\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"metrics\": {},\n  \"model_type\": \"example_string\",\n  \"qdrant_collection\": {},\n  \"status\": \"example_string\",\n  \"version_tag\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.model_versions.create(version_tag='v2.0', checkpoint_path='...')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/model-versions\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"artifact_uri\\\": {}, \\\"metrics\\\": {}, \\\"model_type\\\": \\\"example_string\\\", \\\"version_tag\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.model_versions.create(version_tag='v2.0', checkpoint_path='...')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/model-versions', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"artifact_uri\": {},\n  \"metrics\": {},\n  \"model_type\": \"example_string\",\n  \"version_tag\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-model-versions-version-id",
    "group": "models",
    "method": "GET",
    "path": "/v1/model-versions/{version_id}",
    "summary": "Get Model Version",
    "description": "Get Model Version",
    "scope": "models:read",
    "auth": "bearer",
    "parameters": [
      {
        "name": "version_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"activated_at\": {},\n  \"artifact_uri\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"metrics\": {},\n  \"model_type\": \"example_string\",\n  \"qdrant_collection\": {},\n  \"status\": \"example_string\",\n  \"version_tag\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.model_versions.get(version_id='ver-123')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/model-versions/{version_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.model_versions.get(version_id='ver-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/model-versions/{version_id}', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-model-versions-version-id-activate",
    "group": "models",
    "method": "POST",
    "path": "/v1/model-versions/{version_id}:activate",
    "summary": "Activate Model Version",
    "description": "Activate Model Version",
    "scope": "models:deploy",
    "auth": "bearer",
    "parameters": [
      {
        "name": "version_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": false,
      "contentType": "application/json",
      "schemaSummary": "Payload",
      "exampleJson": "{}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"activated_at\": {},\n  \"artifact_uri\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"metrics\": {},\n  \"model_type\": \"example_string\",\n  \"qdrant_collection\": {},\n  \"status\": \"example_string\",\n  \"version_tag\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.model_versions.activate(version_id='ver-123')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/model-versions/{version_id}:activate\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.model_versions.activate(version_id='ver-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/model-versions/{version_id}:activate', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-model-versions-version-id-archive",
    "group": "models",
    "method": "POST",
    "path": "/v1/model-versions/{version_id}:archive",
    "summary": "Archive Model Version",
    "description": "Archive Model Version",
    "scope": "models:write",
    "auth": "bearer",
    "parameters": [
      {
        "name": "version_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": false,
      "contentType": "application/json",
      "schemaSummary": "Payload",
      "exampleJson": "{}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"activated_at\": {},\n  \"artifact_uri\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"metrics\": {},\n  \"model_type\": \"example_string\",\n  \"qdrant_collection\": {},\n  \"status\": \"example_string\",\n  \"version_tag\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.model_versions.archive(version_id='ver-123')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/model-versions/{version_id}:archive\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.model_versions.archive(version_id='ver-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/model-versions/{version_id}:archive', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-model-versions-version-id-rollback",
    "group": "models",
    "method": "POST",
    "path": "/v1/model-versions/{version_id}:rollback",
    "summary": "Rollback To Version",
    "description": "Roll back to the retained version ``version_id`` (A-36: same as the\nolder ``/v1/models/{model_id}:rollback``, whose parameter is a version id).",
    "scope": "models:deploy",
    "auth": "bearer",
    "parameters": [
      {
        "name": "version_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": false,
      "contentType": "application/json",
      "schemaSummary": "Payload",
      "exampleJson": "{}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"activated_at\": {},\n  \"artifact_uri\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"metrics\": {},\n  \"model_type\": \"example_string\",\n  \"qdrant_collection\": {},\n  \"status\": \"example_string\",\n  \"version_tag\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.model_versions.rollback(version_id='ver-123')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/model-versions/{version_id}:rollback\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.model_versions.rollback(version_id='ver-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/model-versions/{version_id}:rollback', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-models-model-id-rollback",
    "group": "models",
    "method": "POST",
    "path": "/v1/models/{model_id}:rollback",
    "summary": "Rollback Model",
    "description": "Rollback Model",
    "scope": null,
    "auth": "apiKey",
    "parameters": [
      {
        "name": "model_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": false,
      "contentType": "application/json",
      "schemaSummary": "Payload",
      "exampleJson": "{}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"activated_at\": {},\n  \"artifact_uri\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"metrics\": {},\n  \"model_type\": \"example_string\",\n  \"qdrant_collection\": {},\n  \"status\": \"example_string\",\n  \"version_tag\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/models/{model_id}:rollback\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{}\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: POST /v1/models/{model_id}:rollback",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/models/{model_id}:rollback', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-plans",
    "group": "auth",
    "method": "GET",
    "path": "/v1/plans",
    "summary": "List Public Plans",
    "description": "List Public Plans",
    "scope": null,
    "auth": "none",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"code\": \"...\",\n      \"limits\": \"...\",\n      \"name\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.plans()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/plans\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.plans()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/plans', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-audit",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/audit",
    "summary": "List Platform Audit Logs",
    "description": "UC-31: the immutable action history, newest first, filtered and paginated.",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "tenant_id",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "action",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "outcome",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "since",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "Inclusive ISO-8601 start.",
        "example": ""
      },
      {
        "name": "until",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "Exclusive ISO-8601 end.",
        "example": ""
      },
      {
        "name": "before",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "Keyset cursor from next_before.",
        "example": ""
      },
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "type": "integer",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"action_type\": \"...\",\n      \"actor_reference\": \"...\",\n      \"actor_type\": \"...\",\n      \"correlation_reference\": \"...\",\n      \"id\": \"...\",\n      \"occurred_at\": \"...\",\n      \"outcome\": \"...\",\n      \"reason\": \"...\",\n      \"resource_reference\": \"...\",\n      \"resource_type\": \"...\",\n      \"tenant_id\": \"...\"\n    }\n  ],\n  \"next_before\": {}\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/audit\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/audit",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/audit', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-platform-auth-login",
    "group": "platform",
    "method": "POST",
    "path": "/v1/platform/auth/login",
    "summary": "Operator Login",
    "description": "Operator Login",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"email\": \"example_string\",\n  \"password\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"access_token\": \"example_string\",\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"expires_in\": 1,\n  \"operator_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"roles\": [\n    \"platform\"\n  ],\n  \"token_type\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/platform/auth/login\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"email\\\": \\\"example_string\\\", \\\"password\\\": \\\"example_string\\\"}\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: POST /v1/platform/auth/login",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/auth/login', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"email\": \"example_string\",\n  \"password\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-failures",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/failures",
    "summary": "List Platform Failures",
    "description": "List Platform Failures",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"event_type\": \"...\",\n      \"id\": \"...\",\n      \"occurred_at\": \"...\",\n      \"sanitized_detail\": \"...\",\n      \"severity\": \"...\",\n      \"tenant_id\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/failures\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/failures",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/failures', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-me",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/me",
    "summary": "Whoami",
    "description": "Whoami",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"email\": {},\n  \"kind\": \"operator\",\n  \"operator_id\": {},\n  \"roles\": [\n    \"platform\"\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/me\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/me",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/me', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-operators",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/operators",
    "summary": "List Operators",
    "description": "List Operators",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"created_at\": \"...\",\n      \"display_name\": \"...\",\n      \"email\": \"...\",\n      \"id\": \"...\",\n      \"last_login_at\": \"...\",\n      \"roles\": \"...\",\n      \"status\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/operators\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/operators",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/operators', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-platform-operators",
    "group": "platform",
    "method": "POST",
    "path": "/v1/platform/operators",
    "summary": "Create Operator",
    "description": "Create Operator",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"password\": \"example_string\",\n  \"roles\": [\n    \"platform\"\n  ]\n}"
    },
    "responses": [
      {
        "status": 201,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_login_at\": {},\n  \"roles\": [\n    \"platform\"\n  ],\n  \"status\": \"active\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/platform/operators\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"display_name\\\": \\\"example_string\\\", \\\"email\\\": \\\"example_string\\\", \\\"password\\\": \\\"example_string\\\", \\\"roles\\\": [\\\"platform\\\"]}\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: POST /v1/platform/operators",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/operators', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"password\": \"example_string\",\n  \"roles\": [\n    \"platform\"\n  ]\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "patch-v1-platform-operators-operator-id",
    "group": "platform",
    "method": "PATCH",
    "path": "/v1/platform/operators/{operator_id}",
    "summary": "Update Operator",
    "description": "Update Operator",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "operator_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"display_name\": {},\n  \"password\": {},\n  \"roles\": {},\n  \"status\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_login_at\": {},\n  \"roles\": [\n    \"platform\"\n  ],\n  \"status\": \"active\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X PATCH \"https://api.graphrec.io/v1/platform/operators/{operator_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"display_name\\\": {}, \\\"password\\\": {}, \\\"roles\\\": {}, \\\"status\\\": {}}\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: PATCH /v1/platform/operators/{operator_id}",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/operators/{operator_id}', {\n  method: 'PATCH',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"display_name\": {},\n  \"password\": {},\n  \"roles\": {},\n  \"status\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-plans",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/plans",
    "summary": "List Platform Plans",
    "description": "List Platform Plans",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "[\n  {\n    \"code\": \"example_string\",\n    \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n    \"is_active\": true,\n    \"limits\": {},\n    \"name\": \"example_string\",\n    \"warnings\": [\n      {}\n    ]\n  }\n]"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/plans\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/plans",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/plans', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "put-v1-platform-plans-plan-id",
    "group": "platform",
    "method": "PUT",
    "path": "/v1/platform/plans/{plan_id}",
    "summary": "Update Platform Plan",
    "description": "Update Platform Plan",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "plan_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"acknowledge_below_usage\": true,\n  \"is_active\": true,\n  \"limits\": {},\n  \"name\": \"example_string\",\n  \"reason\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"code\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"is_active\": true,\n  \"limits\": {},\n  \"name\": \"example_string\",\n  \"warnings\": [\n    {}\n  ]\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X PUT \"https://api.graphrec.io/v1/platform/plans/{plan_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"acknowledge_below_usage\\\": true, \\\"is_active\\\": true, \\\"limits\\\": {}, \\\"name\\\": \\\"example_string\\\", \\\"reason\\\": {}}\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: PUT /v1/platform/plans/{plan_id}",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/plans/{plan_id}', {\n  method: 'PUT',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"acknowledge_below_usage\": true,\n  \"is_active\": true,\n  \"limits\": {},\n  \"name\": \"example_string\",\n  \"reason\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-status",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/status",
    "summary": "Get Platform Status",
    "description": "Get Platform Status",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"api_cluster\": \"example_string\",\n  \"database\": \"example_string\",\n  \"deployments\": {},\n  \"rate_limiter\": {\n    \"backend\": \"example_string\",\n    \"fail_open_total\": 1,\n    \"last_error_at\": {},\n    \"status\": \"example_string\"\n  },\n  \"status\": \"example_string\",\n  \"timestamp\": \"2026-10-10T12:00:00Z\",\n  \"worker_pool\": \"example_string\"\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/status\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/status",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/status', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-tenants",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/tenants",
    "summary": "List Platform Tenants",
    "description": "List Platform Tenants",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"created_at\": \"...\",\n      \"id\": \"...\",\n      \"name\": \"...\",\n      \"slug\": \"...\",\n      \"status\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/tenants\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/tenants",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/tenants', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-tenants-tenant-id",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/tenants/{tenant_id}",
    "summary": "Get Platform Tenant",
    "description": "Get Platform Tenant",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "tenant_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"name\": \"example_string\",\n  \"slug\": \"example_string\",\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/tenants/{tenant_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/tenants/{tenant_id}",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/tenants/{tenant_id}', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-platform-tenants-tenant-id-plan",
    "group": "platform",
    "method": "POST",
    "path": "/v1/platform/tenants/{tenant_id}/plan",
    "summary": "Assign Tenant Plan",
    "description": "Assign Tenant Plan",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "tenant_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"acknowledge_below_usage\": true,\n  \"plan_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"reason\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"limits\": {},\n  \"overrides\": {},\n  \"plan_code\": \"example_string\",\n  \"plan_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"warnings\": [\n    {}\n  ]\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/platform/tenants/{tenant_id}/plan\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"acknowledge_below_usage\\\": true, \\\"plan_id\\\": \\\"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\\\", \\\"reason\\\": {}}\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: POST /v1/platform/tenants/{tenant_id}/plan",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/tenants/{tenant_id}/plan', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"acknowledge_below_usage\": true,\n  \"plan_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"reason\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-tenants-tenant-id-quotas",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/tenants/{tenant_id}/quotas",
    "summary": "Get Tenant Quota",
    "description": "Get Tenant Quota",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "tenant_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"limits\": {},\n  \"overrides\": {},\n  \"plan_code\": \"example_string\",\n  \"plan_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/tenants/{tenant_id}/quotas\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/tenants/{tenant_id}/quotas",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/tenants/{tenant_id}/quotas', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-platform-tenants-tenant-id-quotas",
    "group": "platform",
    "method": "POST",
    "path": "/v1/platform/tenants/{tenant_id}/quotas",
    "summary": "Set Tenant Quota Override",
    "description": "Set Tenant Quota Override",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "tenant_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"acknowledge_below_usage\": true,\n  \"overrides\": {},\n  \"reason\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"limits\": {},\n  \"overrides\": {},\n  \"warnings\": [\n    {}\n  ]\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/platform/tenants/{tenant_id}/quotas\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"acknowledge_below_usage\\\": true, \\\"overrides\\\": {}, \\\"reason\\\": {}}\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: POST /v1/platform/tenants/{tenant_id}/quotas",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/tenants/{tenant_id}/quotas', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"acknowledge_below_usage\": true,\n  \"overrides\": {},\n  \"reason\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-platform-tenants-tenant-id-recovery",
    "group": "platform",
    "method": "POST",
    "path": "/v1/platform/tenants/{tenant_id}/recovery",
    "summary": "Issue Account Recovery",
    "description": "Issue Account Recovery",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "tenant_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"email\": \"example_string\",\n  \"reason\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"expires_at\": \"2026-10-10T12:00:00Z\",\n  \"recovery_token\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/platform/tenants/{tenant_id}/recovery\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"email\\\": \\\"example_string\\\", \\\"reason\\\": {}}\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: POST /v1/platform/tenants/{tenant_id}/recovery",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/tenants/{tenant_id}/recovery', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"email\": \"example_string\",\n  \"reason\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-platform-tenants-tenant-id-status",
    "group": "platform",
    "method": "POST",
    "path": "/v1/platform/tenants/{tenant_id}/status",
    "summary": "Update Platform Tenant Status",
    "description": "Update Platform Tenant Status",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "tenant_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"reason\": \"example_string\",\n  \"status\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"name\": \"example_string\",\n  \"slug\": \"example_string\",\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/platform/tenants/{tenant_id}/status\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"reason\\\": \\\"example_string\\\", \\\"status\\\": \\\"example_string\\\"}\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: POST /v1/platform/tenants/{tenant_id}/status",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/tenants/{tenant_id}/status', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"reason\": \"example_string\",\n  \"status\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-tenants-tenant-id-usage",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/tenants/{tenant_id}/usage",
    "summary": "Get Tenant Usage",
    "description": "Get Tenant Usage",
    "scope": null,
    "auth": "bearer",
    "parameters": [
      {
        "name": "tenant_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"current_period\": true,\n  \"dimensions\": [\n    {\n      \"limit\": \"...\",\n      \"measured\": \"...\",\n      \"remaining\": \"...\",\n      \"scope\": \"...\",\n      \"type\": \"...\",\n      \"unit\": \"...\",\n      \"used\": \"...\"\n    }\n  ],\n  \"last_reconciled_at\": \"2026-10-10T12:00:00Z\",\n  \"period_end\": \"2026-10-10T12:00:00Z\",\n  \"period_start\": \"2026-10-10T12:00:00Z\",\n  \"project_defaults\": true,\n  \"reset_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/tenants/{tenant_id}/usage\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/tenants/{tenant_id}/usage",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/tenants/{tenant_id}/usage', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-platform-usage",
    "group": "platform",
    "method": "GET",
    "path": "/v1/platform/usage",
    "summary": "List Platform Usage",
    "description": "UC-29: every tenant's usage against its limits for the current period.\nAggregates only; no customer or event payloads leave this endpoint.",
    "scope": null,
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"dimensions\": \"...\",\n      \"name\": \"...\",\n      \"period_start\": \"...\",\n      \"plan_code\": \"...\",\n      \"status\": \"...\",\n      \"tenant_id\": \"...\",\n      \"unavailable\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": null,
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/platform/usage\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "# Direct client call via SyncAPIClient\nfrom graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\n# Endpoint: GET /v1/platform/usage",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/platform/usage', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-products",
    "group": "catalog",
    "method": "GET",
    "path": "/v1/products",
    "summary": "List Products",
    "description": "List products newest first. ``total`` counts every match, not just this page.",
    "scope": "catalog:read",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "limit",
        "in": "query",
        "required": false,
        "type": "integer",
        "description": "",
        "example": ""
      },
      {
        "name": "offset",
        "in": "query",
        "required": false,
        "type": "integer",
        "description": "",
        "example": ""
      },
      {
        "name": "ids",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "Comma-separated external ids (at most 200) to fetch directly",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"availability_status\": \"...\",\n      \"category\": \"...\",\n      \"created_at\": \"...\",\n      \"description\": \"...\",\n      \"external_id\": \"...\",\n      \"id\": \"...\",\n      \"is_active\": \"...\",\n      \"metadata\": \"...\",\n      \"price\": \"...\",\n      \"title\": \"...\",\n      \"updated_at\": \"...\"\n    }\n  ],\n  \"total\": 1\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.catalog.list(limit=50)",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/products\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.catalog.list(limit=50)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/products', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-products-external-id",
    "group": "catalog",
    "method": "GET",
    "path": "/v1/products/{external_id}",
    "summary": "Get Product",
    "description": "Get Product",
    "scope": "catalog:read",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "external_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"availability_status\": \"example_string\",\n  \"category\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"description\": {},\n  \"external_id\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"is_active\": true,\n  \"metadata\": {},\n  \"price\": \"example_string\",\n  \"title\": \"example_string\",\n  \"updated_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.catalog.get(external_id='SKU-100')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/products/{external_id}\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.catalog.get(external_id='SKU-100')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/products/{external_id}', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "patch-v1-products-external-id",
    "group": "catalog",
    "method": "PATCH",
    "path": "/v1/products/{external_id}",
    "summary": "Patch Product",
    "description": "Patch Product",
    "scope": "catalog:write",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "external_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"availability_status\": \"available\",\n  \"category\": {},\n  \"description\": {},\n  \"external_id\": \"example_string\",\n  \"is_active\": true,\n  \"metadata\": {},\n  \"price\": {},\n  \"title\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"availability_status\": \"example_string\",\n  \"category\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"description\": {},\n  \"external_id\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"is_active\": true,\n  \"metadata\": {},\n  \"price\": \"example_string\",\n  \"title\": \"example_string\",\n  \"updated_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.catalog.update(external_id='SKU-100', patch={'price': '44.90'})",
    "examples": {
      "curl": "curl -X PATCH \"https://api.graphrec.io/v1/products/{external_id}\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"availability_status\\\": \\\"available\\\", \\\"category\\\": {}, \\\"description\\\": {}, \\\"external_id\\\": \\\"example_string\\\", \\\"is_active\\\": true, \\\"metadata\\\": {}, \\\"price\\\": {}, \\\"title\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.catalog.update(external_id='SKU-100', patch={'price': '44.90'})\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/products/{external_id}', {\n  method: 'PATCH',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"availability_status\": \"available\",\n  \"category\": {},\n  \"description\": {},\n  \"external_id\": \"example_string\",\n  \"is_active\": true,\n  \"metadata\": {},\n  \"price\": {},\n  \"title\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "put-v1-products-external-id",
    "group": "catalog",
    "method": "PUT",
    "path": "/v1/products/{external_id}",
    "summary": "Put Product",
    "description": "Put Product",
    "scope": "catalog:write",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "external_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"availability_status\": \"available\",\n  \"category\": {},\n  \"description\": {},\n  \"external_id\": \"example_string\",\n  \"is_active\": true,\n  \"metadata\": {},\n  \"price\": {},\n  \"title\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"availability_status\": \"example_string\",\n  \"category\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"description\": {},\n  \"external_id\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"is_active\": true,\n  \"metadata\": {},\n  \"price\": \"example_string\",\n  \"title\": \"example_string\",\n  \"updated_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.catalog.upsert(external_id='SKU-100', product={'title': 'Linen Shirt', 'price': '49.90', 'category': 'Apparel'})",
    "examples": {
      "curl": "curl -X PUT \"https://api.graphrec.io/v1/products/{external_id}\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"availability_status\\\": \\\"available\\\", \\\"category\\\": {}, \\\"description\\\": {}, \\\"external_id\\\": \\\"example_string\\\", \\\"is_active\\\": true, \\\"metadata\\\": {}, \\\"price\\\": {}, \\\"title\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.catalog.upsert(external_id='SKU-100', product={'title': 'Linen Shirt', 'price': '49.90', 'category': 'Apparel'})\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/products/{external_id}', {\n  method: 'PUT',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"availability_status\": \"available\",\n  \"category\": {},\n  \"description\": {},\n  \"external_id\": \"example_string\",\n  \"is_active\": true,\n  \"metadata\": {},\n  \"price\": {},\n  \"title\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-products-external-id-disable",
    "group": "catalog",
    "method": "POST",
    "path": "/v1/products/{external_id}:disable",
    "summary": "Disable Product",
    "description": "Disable Product",
    "scope": "catalog:write",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "external_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"availability_status\": \"example_string\",\n  \"category\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"description\": {},\n  \"external_id\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"is_active\": true,\n  \"metadata\": {},\n  \"price\": \"example_string\",\n  \"title\": \"example_string\",\n  \"updated_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.catalog.disable(external_id='SKU-100')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/products/{external_id}:disable\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.catalog.disable(external_id='SKU-100')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/products/{external_id}:disable', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-products-bulk-upsert",
    "group": "catalog",
    "method": "POST",
    "path": "/v1/products:bulk-upsert",
    "summary": "Bulk Upsert Products",
    "description": "Bulk Upsert Products",
    "scope": "catalog:write",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"products\": [\n    {\n      \"availability_status\": \"...\",\n      \"category\": \"...\",\n      \"description\": \"...\",\n      \"external_id\": \"...\",\n      \"is_active\": \"...\",\n      \"metadata\": \"...\",\n      \"price\": \"...\",\n      \"title\": \"...\"\n    }\n  ],\n  \"request_id\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"accepted_count\": 1,\n  \"created_count\": 1,\n  \"failures\": [\n    {\n      \"external_id\": \"...\",\n      \"reason\": \"...\"\n    }\n  ],\n  \"outcomes\": [\n    {}\n  ],\n  \"rejected_count\": 1,\n  \"request_id\": {},\n  \"skipped_count\": 1,\n  \"status\": \"example_string\",\n  \"sync_id\": {},\n  \"updated_count\": 1\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.catalog.bulk_upsert(products=[{'external_id': 'SKU-100', 'title': 'Linen Shirt', 'price': '49.90', 'category': 'Apparel'}])",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/products:bulk-upsert\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"products\\\": [{\\\"availability_status\\\": \\\"...\\\", \\\"category\\\": \\\"...\\\", \\\"description\\\": \\\"...\\\", \\\"external_id\\\": \\\"...\\\", \\\"is_active\\\": \\\"...\\\", \\\"metadata\\\": \\\"...\\\", \\\"price\\\": \\\"...\\\", \\\"title\\\": \\\"...\\\"}], \\\"request_id\\\": {}}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.catalog.bulk_upsert(products=[{'external_id': 'SKU-100', 'title': 'Linen Shirt', 'price': '49.90', 'category': 'Apparel'}])\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/products:bulk-upsert', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"products\": [\n    {\n      \"availability_status\": \"...\",\n      \"category\": \"...\",\n      \"description\": \"...\",\n      \"external_id\": \"...\",\n      \"is_active\": \"...\",\n      \"metadata\": \"...\",\n      \"price\": \"...\",\n      \"title\": \"...\"\n    }\n  ],\n  \"request_id\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-recommendation-policy",
    "group": "recommendations",
    "method": "GET",
    "path": "/v1/recommendation-policy",
    "summary": "Get Recommendation Policy",
    "description": "Get Recommendation Policy",
    "scope": "models:read",
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"configured\": true,\n  \"diversity_enabled\": true,\n  \"freshness_enabled\": true,\n  \"freshness_half_life_days\": 1,\n  \"freshness_weight\": 1,\n  \"max_per_category\": 1,\n  \"tenant_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"updated_at\": {},\n  \"version\": 1\n}"
      }
    ],
    "sdkMethod": "client.tenant.recommendation_policy.get()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/recommendation-policy\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.recommendation_policy.get()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/recommendation-policy', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "put-v1-recommendation-policy",
    "group": "recommendations",
    "method": "PUT",
    "path": "/v1/recommendation-policy",
    "summary": "Put Recommendation Policy",
    "description": "Put Recommendation Policy",
    "scope": "models:deploy",
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"diversity_enabled\": true,\n  \"freshness_enabled\": true,\n  \"freshness_half_life_days\": 1,\n  \"freshness_weight\": 1,\n  \"max_per_category\": 1\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"configured\": true,\n  \"diversity_enabled\": true,\n  \"freshness_enabled\": true,\n  \"freshness_half_life_days\": 1,\n  \"freshness_weight\": 1,\n  \"max_per_category\": 1,\n  \"tenant_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"updated_at\": {},\n  \"version\": 1\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.recommendation_policy.update(max_category_share=0.4, freshness_boost_hours=48)",
    "examples": {
      "curl": "curl -X PUT \"https://api.graphrec.io/v1/recommendation-policy\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"diversity_enabled\\\": true, \\\"freshness_enabled\\\": true, \\\"freshness_half_life_days\\\": 1, \\\"freshness_weight\\\": 1, \\\"max_per_category\\\": 1}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.recommendation_policy.update(max_category_share=0.4, freshness_boost_hours=48)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/recommendation-policy', {\n  method: 'PUT',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"diversity_enabled\": true,\n  \"freshness_enabled\": true,\n  \"freshness_half_life_days\": 1,\n  \"freshness_weight\": 1,\n  \"max_per_category\": 1\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-recommendations",
    "group": "recommendations",
    "method": "POST",
    "path": "/v1/recommendations",
    "summary": "Get Recommendations",
    "description": "Serve Top-N recommendations and record what it took to serve them.",
    "scope": "recommendations:read",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"context\": {\n    \"recent_product_ids\": {},\n    \"session_id\": {},\n    \"surface\": {}\n  },\n  \"diversity\": {},\n  \"exclude_product_ids\": [\n    \"example_string\"\n  ],\n  \"explain\": true,\n  \"fallback_allowed\": true,\n  \"request_id\": {},\n  \"top_n\": 1,\n  \"user_id\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"active_model_version_id\": {},\n  \"applied_rules\": [\n    \"example_string\"\n  ],\n  \"diversity\": {},\n  \"explain\": {},\n  \"fallback_tier\": \"example_string\",\n  \"fallback_used\": true,\n  \"items\": [\n    {\n      \"anchor_product_id\": \"...\",\n      \"external_product_id\": \"...\",\n      \"position\": \"...\",\n      \"reason\": \"...\",\n      \"score\": \"...\",\n      \"sources\": \"...\"\n    }\n  ],\n  \"model_version_id\": {},\n  \"pipeline\": {},\n  \"request_id\": \"example_string\",\n  \"rules_version\": {},\n  \"strategy\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.storefront.recommendations.get(user_id='cus-9931', top_n=10, context={'surface': 'cart'})",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/recommendations\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"context\\\": {\\\"recent_product_ids\\\": {}, \\\"session_id\\\": {}, \\\"surface\\\": {}}, \\\"diversity\\\": {}, \\\"exclude_product_ids\\\": [\\\"example_string\\\"], \\\"explain\\\": true, \\\"fallback_allowed\\\": true, \\\"request_id\\\": {}, \\\"top_n\\\": 1, \\\"user_id\\\": {}}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.recommendations.get(user_id='cus-9931', top_n=10, context={'surface': 'cart'})\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/recommendations', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"context\": {\n    \"recent_product_ids\": {},\n    \"session_id\": {},\n    \"surface\": {}\n  },\n  \"diversity\": {},\n  \"exclude_product_ids\": [\n    \"example_string\"\n  ],\n  \"explain\": true,\n  \"fallback_allowed\": true,\n  \"request_id\": {},\n  \"top_n\": 1,\n  \"user_id\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-recommendations-session",
    "group": "recommendations",
    "method": "POST",
    "path": "/v1/recommendations/session",
    "summary": "Get Session Recommendations",
    "description": "Get Session Recommendations",
    "scope": "recommendations:read",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"context\": {\n    \"recent_product_ids\": {},\n    \"session_id\": {},\n    \"surface\": {}\n  },\n  \"diversity\": {},\n  \"exclude_product_ids\": [\n    \"example_string\"\n  ],\n  \"explain\": true,\n  \"fallback_allowed\": true,\n  \"request_id\": {},\n  \"top_n\": 1,\n  \"user_id\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"active_model_version_id\": {},\n  \"applied_rules\": [\n    \"example_string\"\n  ],\n  \"diversity\": {},\n  \"explain\": {},\n  \"fallback_tier\": \"example_string\",\n  \"fallback_used\": true,\n  \"items\": [\n    {\n      \"anchor_product_id\": \"...\",\n      \"external_product_id\": \"...\",\n      \"position\": \"...\",\n      \"reason\": \"...\",\n      \"score\": \"...\",\n      \"sources\": \"...\"\n    }\n  ],\n  \"model_version_id\": {},\n  \"pipeline\": {},\n  \"request_id\": \"example_string\",\n  \"rules_version\": {},\n  \"strategy\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.storefront.recommendations.for_session(item_ids=['SKU-100', 'SKU-200'], top_n=10)",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/recommendations/session\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"context\\\": {\\\"recent_product_ids\\\": {}, \\\"session_id\\\": {}, \\\"surface\\\": {}}, \\\"diversity\\\": {}, \\\"exclude_product_ids\\\": [\\\"example_string\\\"], \\\"explain\\\": true, \\\"fallback_allowed\\\": true, \\\"request_id\\\": {}, \\\"top_n\\\": 1, \\\"user_id\\\": {}}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.storefront.recommendations.for_session(item_ids=['SKU-100', 'SKU-200'], top_n=10)\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/recommendations/session', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"context\": {\n    \"recent_product_ids\": {},\n    \"session_id\": {},\n    \"surface\": {}\n  },\n  \"diversity\": {},\n  \"exclude_product_ids\": [\n    \"example_string\"\n  ],\n  \"explain\": true,\n  \"fallback_allowed\": true,\n  \"request_id\": {},\n  \"top_n\": 1,\n  \"user_id\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-retraining-policy",
    "group": "models",
    "method": "GET",
    "path": "/v1/retraining-policy",
    "summary": "Get Retraining Policy",
    "description": "Get Retraining Policy",
    "scope": "training:read",
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"configured\": true,\n  \"epochs\": 1,\n  \"event_threshold\": 1,\n  \"event_trigger_enabled\": true,\n  \"interval_minutes\": 1,\n  \"last_evaluated_at\": {},\n  \"last_job_id\": {},\n  \"last_outcome\": {},\n  \"last_outcome_at\": {},\n  \"last_outcome_detail\": {},\n  \"last_training_requested_at\": {},\n  \"last_trigger\": {}\n}"
      }
    ],
    "sdkMethod": "client.tenant.retraining_policy.get()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/retraining-policy\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.retraining_policy.get()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/retraining-policy', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "put-v1-retraining-policy",
    "group": "models",
    "method": "PUT",
    "path": "/v1/retraining-policy",
    "summary": "Put Retraining Policy",
    "description": "Put Retraining Policy",
    "scope": "training:write",
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"epochs\": 1,\n  \"event_threshold\": 1,\n  \"event_trigger_enabled\": true,\n  \"interval_minutes\": 1,\n  \"schedule_enabled\": true\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"configured\": true,\n  \"epochs\": 1,\n  \"event_threshold\": 1,\n  \"event_trigger_enabled\": true,\n  \"interval_minutes\": 1,\n  \"last_evaluated_at\": {},\n  \"last_job_id\": {},\n  \"last_outcome\": {},\n  \"last_outcome_at\": {},\n  \"last_outcome_detail\": {},\n  \"last_training_requested_at\": {},\n  \"last_trigger\": {}\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.retraining_policy.update(enabled=True, schedule_cron='0 2 * * *')",
    "examples": {
      "curl": "curl -X PUT \"https://api.graphrec.io/v1/retraining-policy\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"epochs\\\": 1, \\\"event_threshold\\\": 1, \\\"event_trigger_enabled\\\": true, \\\"interval_minutes\\\": 1, \\\"schedule_enabled\\\": true}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.retraining_policy.update(enabled=True, schedule_cron='0 2 * * *')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/retraining-policy', {\n  method: 'PUT',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"epochs\": 1,\n  \"event_threshold\": 1,\n  \"event_trigger_enabled\": true,\n  \"interval_minutes\": 1,\n  \"schedule_enabled\": true\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-subscription",
    "group": "management",
    "method": "GET",
    "path": "/v1/subscription",
    "summary": "Get Subscription",
    "description": "Get Subscription",
    "scope": "billing:read",
    "auth": "apiKey",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"limits\": {},\n  \"period_end\": \"2026-10-10T12:00:00Z\",\n  \"period_start\": \"2026-10-10T12:00:00Z\",\n  \"plan_code\": \"free\",\n  \"project_defaults\": true,\n  \"status\": \"example_string\"\n}"
      }
    ],
    "sdkMethod": "client.tenant.subscription.get()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/subscription\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.subscription.get()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/subscription', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-tenant-status",
    "group": "management",
    "method": "GET",
    "path": "/v1/tenant/status",
    "summary": "Get Tenant Status",
    "description": "Any signed-in member may read the workspace status; a member of a suspended\nworkspace can read only this (D-13). API keys are not accepted.",
    "scope": "status:read",
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"message\": \"example_string\",\n  \"name\": \"example_string\",\n  \"restricted_session\": true,\n  \"status\": \"active\",\n  \"tenant_id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\"\n}"
      }
    ],
    "sdkMethod": "client.tenant.account.status()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/tenant/status\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.account.status()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/tenant/status', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-tenant-users",
    "group": "management",
    "method": "GET",
    "path": "/v1/tenant/users",
    "summary": "List Tenant Users",
    "description": "List Tenant Users",
    "scope": "users:write",
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"created_at\": \"...\",\n      \"display_name\": \"...\",\n      \"email\": \"...\",\n      \"id\": \"...\",\n      \"last_authenticated_at\": \"...\",\n      \"role\": \"...\",\n      \"status\": \"...\"\n    }\n  ],\n  \"total\": 1\n}"
      }
    ],
    "sdkMethod": "client.tenant.users.list()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/tenant/users\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.users.list()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/tenant/users', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-tenant-users",
    "group": "management",
    "method": "POST",
    "path": "/v1/tenant/users",
    "summary": "Invite Tenant User",
    "description": "Invite Tenant User",
    "scope": "users:write",
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"display_name\": {},\n  \"email\": \"example_string\",\n  \"role\": \"tenant_administrator\"\n}"
    },
    "responses": [
      {
        "status": 201,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_authenticated_at\": {},\n  \"next_step\": \"example_string\",\n  \"role\": \"example_string\",\n  \"setup_token\": \"example_string\",\n  \"setup_token_expires_at\": \"2026-10-10T12:00:00Z\",\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.users.invite(email='dev@example.com', role='tenant_developer')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/tenant/users\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"display_name\\\": {}, \\\"email\\\": \\\"example_string\\\", \\\"role\\\": \\\"tenant_administrator\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.users.invite(email='dev@example.com', role='tenant_developer')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/tenant/users', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"display_name\": {},\n  \"email\": \"example_string\",\n  \"role\": \"tenant_administrator\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-tenant-users-user-id",
    "group": "management",
    "method": "GET",
    "path": "/v1/tenant/users/{user_id}",
    "summary": "Get Tenant User",
    "description": "Get Tenant User",
    "scope": "users:write",
    "auth": "bearer",
    "parameters": [
      {
        "name": "user_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_authenticated_at\": {},\n  \"role\": \"example_string\",\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.users.get(user_id='user-123')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/tenant/users/{user_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.users.get(user_id='user-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/tenant/users/{user_id}', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "patch-v1-tenant-users-user-id",
    "group": "management",
    "method": "PATCH",
    "path": "/v1/tenant/users/{user_id}",
    "summary": "Update Tenant User",
    "description": "Change a member's role, or lock, unlock or disable the account. Ends the member's sessions.",
    "scope": "users:write",
    "auth": "bearer",
    "parameters": [
      {
        "name": "user_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"reason\": {},\n  \"role\": {},\n  \"status\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_authenticated_at\": {},\n  \"role\": \"example_string\",\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.users.update(user_id='user-123', role='tenant_admin')",
    "examples": {
      "curl": "curl -X PATCH \"https://api.graphrec.io/v1/tenant/users/{user_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"reason\\\": {}, \\\"role\\\": {}, \\\"status\\\": {}}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.users.update(user_id='user-123', role='tenant_admin')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/tenant/users/{user_id}', {\n  method: 'PATCH',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"reason\": {},\n  \"role\": {},\n  \"status\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "delete-v1-tenant-users-user-id-invitation",
    "group": "management",
    "method": "DELETE",
    "path": "/v1/tenant/users/{user_id}/invitation",
    "summary": "Revoke Tenant User Invitation",
    "description": "Withdraw a pending invitation; its one-time setup link stops working.",
    "scope": "users:write",
    "auth": "bearer",
    "parameters": [
      {
        "name": "user_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_authenticated_at\": {},\n  \"role\": \"example_string\",\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.users.revoke_invitation(user_id='user-123')",
    "examples": {
      "curl": "curl -X DELETE \"https://api.graphrec.io/v1/tenant/users/{user_id}/invitation\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.users.revoke_invitation(user_id='user-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/tenant/users/{user_id}/invitation', {\n  method: 'DELETE',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-tenant-users-user-id-invitation-resend",
    "group": "management",
    "method": "POST",
    "path": "/v1/tenant/users/{user_id}/invitation:resend",
    "summary": "Resend Tenant User Invitation",
    "description": "Issue a new one-time setup link for a pending invitation; earlier links stop working.",
    "scope": "users:write",
    "auth": "bearer",
    "parameters": [
      {
        "name": "user_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"display_name\": \"example_string\",\n  \"email\": \"example_string\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"last_authenticated_at\": {},\n  \"next_step\": \"example_string\",\n  \"role\": \"example_string\",\n  \"setup_token\": \"example_string\",\n  \"setup_token_expires_at\": \"2026-10-10T12:00:00Z\",\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.users.resend_invitation(user_id='user-123')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/tenant/users/{user_id}/invitation:resend\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.users.resend_invitation(user_id='user-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/tenant/users/{user_id}/invitation:resend', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-tenants",
    "group": "management",
    "method": "POST",
    "path": "/v1/tenants",
    "summary": "Register Tenant",
    "description": "Register Tenant",
    "scope": null,
    "auth": "none",
    "parameters": [
      {
        "name": "Idempotency-Key",
        "in": "header",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"admin_email\": \"example_string\",\n  \"name\": \"example_string\"\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "OK",
        "exampleJson": "{\n  \"administrator_email\": \"example_string\",\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"name\": \"example_string\",\n  \"next_step\": \"example_string\",\n  \"setup_token\": {},\n  \"setup_token_expires_at\": {},\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 201,
        "description": "Successful Response",
        "exampleJson": "{\n  \"administrator_email\": \"example_string\",\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"name\": \"example_string\",\n  \"next_step\": \"example_string\",\n  \"setup_token\": {},\n  \"setup_token_expires_at\": {},\n  \"status\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.auth.register(business_name='Acme', email='admin@acme.com')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/tenants\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"admin_email\\\": \\\"example_string\\\", \\\"name\\\": \\\"example_string\\\"}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.auth.register(business_name='Acme', email='admin@acme.com')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/tenants', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"admin_email\": \"example_string\",\n  \"name\": \"example_string\"\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-training-jobs",
    "group": "models",
    "method": "GET",
    "path": "/v1/training-jobs",
    "summary": "List Training Jobs",
    "description": "List Training Jobs",
    "scope": "training:read",
    "auth": "bearer",
    "parameters": [],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"items\": [\n    {\n      \"cancel_requested\": \"...\",\n      \"completed_at\": \"...\",\n      \"configuration\": \"...\",\n      \"created_at\": \"...\",\n      \"dataset_snapshot_id\": \"...\",\n      \"failure_reason\": \"...\",\n      \"id\": \"...\",\n      \"model_type\": \"...\",\n      \"model_version_id\": \"...\",\n      \"progress\": \"...\",\n      \"qdrant_collection\": \"...\",\n      \"stage\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.training_jobs.list()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/training-jobs\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.training_jobs.list()\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/training-jobs', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-training-jobs",
    "group": "models",
    "method": "POST",
    "path": "/v1/training-jobs",
    "summary": "Create Training Job",
    "description": "Create Training Job",
    "scope": "training:write",
    "auth": "bearer",
    "parameters": [],
    "requestBody": {
      "required": true,
      "contentType": "application/json",
      "schemaSummary": "Request Payload",
      "exampleJson": "{\n  \"configuration\": {},\n  \"dataset_snapshot_id\": {},\n  \"model_type\": \"example_string\",\n  \"request_id\": {}\n}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"cancel_requested\": true,\n  \"completed_at\": {},\n  \"configuration\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"dataset_snapshot_id\": {},\n  \"failure_reason\": {},\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"model_type\": \"example_string\",\n  \"model_version_id\": {},\n  \"progress\": 1,\n  \"qdrant_collection\": {},\n  \"stage\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.training_jobs.create(dataset_snapshot_id='snap-123')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/training-jobs\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{\\\"configuration\\\": {}, \\\"dataset_snapshot_id\\\": {}, \\\"model_type\\\": \\\"example_string\\\", \\\"request_id\\\": {}}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.training_jobs.create(dataset_snapshot_id='snap-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/training-jobs', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({\n  \"configuration\": {},\n  \"dataset_snapshot_id\": {},\n  \"model_type\": \"example_string\",\n  \"request_id\": {}\n}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-training-jobs-job-id",
    "group": "models",
    "method": "GET",
    "path": "/v1/training-jobs/{job_id}",
    "summary": "Get Training Job",
    "description": "Get Training Job",
    "scope": "training:read",
    "auth": "bearer",
    "parameters": [
      {
        "name": "job_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"cancel_requested\": true,\n  \"completed_at\": {},\n  \"configuration\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"dataset_snapshot_id\": {},\n  \"failure_reason\": {},\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"model_type\": \"example_string\",\n  \"model_version_id\": {},\n  \"progress\": 1,\n  \"qdrant_collection\": {},\n  \"stage\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.training_jobs.get(job_id='job-123')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/training-jobs/{job_id}\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.training_jobs.get(job_id='job-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/training-jobs/{job_id}', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "post-v1-training-jobs-job-id-cancel",
    "group": "models",
    "method": "POST",
    "path": "/v1/training-jobs/{job_id}:cancel",
    "summary": "Cancel Training Job",
    "description": "Cancel Training Job",
    "scope": "training:write",
    "auth": "bearer",
    "parameters": [
      {
        "name": "job_id",
        "in": "path",
        "required": true,
        "type": "string",
        "description": "",
        "example": ""
      }
    ],
    "requestBody": {
      "required": false,
      "contentType": "application/json",
      "schemaSummary": "Payload",
      "exampleJson": "{}"
    },
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"cancel_requested\": true,\n  \"completed_at\": {},\n  \"configuration\": {},\n  \"created_at\": \"2026-10-10T12:00:00Z\",\n  \"dataset_snapshot_id\": {},\n  \"failure_reason\": {},\n  \"id\": \"5b1f0c9e-7d2a-4c1b-9e83-2f6a0d4b71c5\",\n  \"model_type\": \"example_string\",\n  \"model_version_id\": {},\n  \"progress\": 1,\n  \"qdrant_collection\": {},\n  \"stage\": \"example_string\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.training_jobs.cancel(job_id='job-123')",
    "examples": {
      "curl": "curl -X POST \"https://api.graphrec.io/v1/training-jobs/{job_id}:cancel\" \\\n  -H \"Authorization: Bearer <ACCESS_TOKEN>\" \\\n  -H \"Accept: application/json\" \\\n  -H \"Content-Type: application/json\" \\\n  -d \"{}\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.training_jobs.cancel(job_id='job-123')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/training-jobs/{job_id}:cancel', {\n  method: 'POST',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'Bearer ' + token,\n    'Content-Type': 'application/json',\n  },\n  body: JSON.stringify({}),\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-usage",
    "group": "management",
    "method": "GET",
    "path": "/v1/usage",
    "summary": "Get Usage",
    "description": "Get Usage",
    "scope": "usage:read",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "period",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "UC-24: a monthly billing period, YYYY-MM (default: the current one). Up to 24 months back; never in the future.",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"current_period\": true,\n  \"dimensions\": [\n    {\n      \"limit\": \"...\",\n      \"measured\": \"...\",\n      \"remaining\": \"...\",\n      \"scope\": \"...\",\n      \"type\": \"...\",\n      \"unit\": \"...\",\n      \"used\": \"...\"\n    }\n  ],\n  \"last_reconciled_at\": \"2026-10-10T12:00:00Z\",\n  \"period_end\": \"2026-10-10T12:00:00Z\",\n  \"period_start\": \"2026-10-10T12:00:00Z\",\n  \"project_defaults\": true,\n  \"reset_at\": \"2026-10-10T12:00:00Z\"\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.usage.get(period='current')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/usage\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.usage.get(period='current')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/usage', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-v1-usage-trends",
    "group": "management",
    "method": "GET",
    "path": "/v1/usage/trends",
    "summary": "Get Usage Trends",
    "description": "XR-F-07: usage summarized by period and usage type for the caller's tenant.",
    "scope": "usage:read",
    "auth": "apiKey",
    "parameters": [
      {
        "name": "granularity",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "",
        "example": ""
      },
      {
        "name": "start",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "Inclusive ISO-8601 start (default: 30 days before end).",
        "example": ""
      },
      {
        "name": "end",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "Exclusive ISO-8601 end (default: now).",
        "example": ""
      },
      {
        "name": "types",
        "in": "query",
        "required": false,
        "type": "string",
        "description": "Comma-separated usage types (default: all metered types).",
        "example": ""
      }
    ],
    "requestBody": null,
    "responses": [
      {
        "status": 200,
        "description": "Successful Response",
        "exampleJson": "{\n  \"buckets\": [\n    {\n      \"start\": \"...\",\n      \"values\": \"...\"\n    }\n  ],\n  \"end\": \"2026-10-10T12:00:00Z\",\n  \"granularity\": \"hour\",\n  \"start\": \"2026-10-10T12:00:00Z\",\n  \"tenant_id\": \"example_string\",\n  \"totals\": {},\n  \"usage_types\": [\n    \"example_string\"\n  ]\n}"
      },
      {
        "status": 422,
        "description": "Validation Error",
        "exampleJson": "{\n  \"detail\": [\n    {\n      \"ctx\": \"...\",\n      \"input\": \"...\",\n      \"loc\": \"...\",\n      \"msg\": \"...\",\n      \"type\": \"...\"\n    }\n  ]\n}"
      }
    ],
    "sdkMethod": "client.tenant.usage.trends(granularity='day')",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/v1/usage/trends\" \\\n  -H \"Authorization: ApiKey <YOUR_API_KEY>\" \\\n  -H \"Accept: application/json\"",
      "python": "from graphrec_sdk import GraphRec\n\nclient = GraphRec(api_key='gr_live_...')\nresult = client.tenant.usage.trends(granularity='day')\nprint(result)",
      "javascript": "const response = await fetch('https://api.graphrec.io/v1/usage/trends', {\n  method: 'GET',\n  headers: {\n    'Accept': 'application/json',\n    'Authorization': 'ApiKey ' + apiKey,\n  },\n});\nconst data = await response.json();"
    }
  },
  {
    "id": "get-healthz",
    "group": "serving",
    "method": "GET",
    "path": "/healthz",
    "summary": "Liveness Probe",
    "description": "Liveness check that confirms the HTTP server process is running and can query PostgreSQL.",
    "scope": null,
    "auth": "none",
    "parameters": [],
    "responses": [
      {
        "status": 200,
        "description": "System live",
        "exampleJson": "{\n  \"status\": \"ok\"\n}"
      }
    ],
    "sdkMethod": "client.health()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/healthz\" -H \"Accept: application/json\"",
      "python": "import urllib.request\nprint(urllib.request.urlopen('https://api.graphrec.io/healthz').read().decode())",
      "javascript": "const res = await fetch('https://api.graphrec.io/healthz');\nconst status = await res.json();"
    }
  },
  {
    "id": "get-readyz",
    "group": "serving",
    "method": "GET",
    "path": "/readyz",
    "summary": "Deep Readiness Probe",
    "description": "Deep readiness inspection measuring PostgreSQL, Redis, and Qdrant vector store dependencies.",
    "scope": null,
    "auth": "none",
    "parameters": [],
    "responses": [
      {
        "status": 200,
        "description": "System ready",
        "exampleJson": "{\n  \"status\": \"ready\",\n  \"version\": \"1.1.0\",\n  \"checks\": {\n    \"database\": {\n      \"status\": \"ok\",\n      \"latency_ms\": 1.2\n    },\n    \"redis\": {\n      \"status\": \"ok\",\n      \"latency_ms\": 0.8\n    },\n    \"vector_store\": {\n      \"status\": \"ok\",\n      \"latency_ms\": 2.1\n    }\n  }\n}"
      }
    ],
    "sdkMethod": "client.ready()",
    "examples": {
      "curl": "curl -X GET \"https://api.graphrec.io/readyz\" -H \"Accept: application/json\"",
      "python": "import urllib.request\nprint(urllib.request.urlopen('https://api.graphrec.io/readyz').read().decode())",
      "javascript": "const res = await fetch('https://api.graphrec.io/readyz');\nconst readiness = await res.json();"
    }
  }
];

export const SDK_METHODS: SdkMethodDoc[] = [
  {
    "name": "recommendations.get",
    "namespace": "client.storefront",
    "signature": "client.storefront.recommendations.get(user_id: Optional[str] = None, top_n: int = 10, context: Optional[dict] = None, exclude_product_ids: Optional[list] = None, fallback_allowed: bool = True) -> Recommendations",
    "description": "Fetches real-time personalized recommendations for a known customer using their recent sequential history and trained user vector.",
    "parameters": [
      {
        "name": "user_id",
        "type": "str",
        "required": false,
        "description": "Shopper external ID. If omitted, falls back to popular items or session context."
      },
      {
        "name": "top_n",
        "type": "int",
        "required": false,
        "default": "10",
        "description": "Number of items to return (1-100)."
      },
      {
        "name": "context",
        "type": "dict",
        "required": false,
        "description": "Surface context, e.g. {'surface': 'cart', 'category': 'Shoes'}."
      },
      {
        "name": "exclude_product_ids",
        "type": "list[str]",
        "required": false,
        "description": "Product IDs to exclude from the recommendation shelf."
      },
      {
        "name": "fallback_allowed",
        "type": "bool",
        "required": false,
        "default": "True",
        "description": "Whether to return popular fallback if personalized inference is unavailable."
      }
    ],
    "returns": "Recommendations (items: list[RecommendationItem], model_version_id: str, strategy: str, fallback_used: bool)",
    "raises": [
      "AuthenticationError",
      "InputValidationError",
      "QuotaExceededError",
      "RateLimitError"
    ],
    "example": "recs = client.storefront.recommendations.get(\n    user_id='customer-42',\n    top_n=10,\n    context={'surface': 'home'}\n)\nfor item in recs.items:\n    print(f'#{item.position}: {item.external_product_id}')"
  },
  {
    "name": "recommendations.for_session",
    "namespace": "client.storefront",
    "signature": "client.storefront.recommendations.for_session(item_ids: Sequence[str], top_n: int = 10, context: Optional[dict] = None) -> Recommendations",
    "description": "Generates session-based sequence recommendations for anonymous visitors using recent in-session item interactions and the global mean user vector.",
    "parameters": [
      {
        "name": "item_ids",
        "type": "Sequence[str]",
        "required": true,
        "description": "Ordered sequence of product external IDs interacted with during the session (up to 20)."
      },
      {
        "name": "top_n",
        "type": "int",
        "required": false,
        "default": "10",
        "description": "Number of items to return."
      },
      {
        "name": "context",
        "type": "dict",
        "required": false,
        "description": "Surface context dictionary."
      }
    ],
    "returns": "Recommendations object with strategy='session'.",
    "raises": [
      "AuthenticationError",
      "InputValidationError",
      "RateLimitError"
    ],
    "example": "recs = client.storefront.recommendations.for_session(\n    item_ids=['SKU-101', 'SKU-205'],\n    top_n=8\n)"
  },
  {
    "name": "feedback.impression",
    "namespace": "client.storefront",
    "signature": "client.storefront.feedback.impression(recommendation: Union[Recommendations, str], items: Sequence[str]) -> FeedbackReceipt",
    "description": "Records recommendation shelf impressions to measure CTR and close the attribution loop.",
    "parameters": [
      {
        "name": "recommendation",
        "type": "Union[Recommendations, str]",
        "required": true,
        "description": "Recommendations instance or request_id UUID."
      },
      {
        "name": "items",
        "type": "Sequence[str]",
        "required": true,
        "description": "Product IDs displayed on screen to the customer."
      }
    ],
    "returns": "FeedbackReceipt (accepted: bool, feedback_id: str)",
    "raises": [
      "AuthenticationError",
      "NotFoundError"
    ],
    "example": "client.storefront.feedback.impression(\n    recommendation=recs.request_id,\n    items=[item.external_product_id for item in recs.items]\n)"
  },
  {
    "name": "feedback.click",
    "namespace": "client.storefront",
    "signature": "client.storefront.feedback.click(recommendation: Union[Recommendations, str], item: str, position: int) -> FeedbackReceipt",
    "description": "Attributes a customer click to a previously served recommendation request.",
    "parameters": [
      {
        "name": "recommendation",
        "type": "Union[Recommendations, str]",
        "required": true,
        "description": "Request ID of the recommendation result."
      },
      {
        "name": "item",
        "type": "str",
        "required": true,
        "description": "External ID of the clicked product."
      },
      {
        "name": "position",
        "type": "int",
        "required": true,
        "description": "Rank position where the item appeared (1-indexed)."
      }
    ],
    "returns": "FeedbackReceipt",
    "raises": [
      "AuthenticationError",
      "NotFoundError"
    ],
    "example": "client.storefront.feedback.click(\n    recommendation='5b1f0c9e-...',\n    item='SKU-100',\n    position=1\n)"
  },
  {
    "name": "feedback.conversion",
    "namespace": "client.storefront",
    "signature": "client.storefront.feedback.conversion(recommendation: Union[Recommendations, str], item: str, value: float = 0.0) -> FeedbackReceipt",
    "description": "Attributes a product purchase conversion to the recommendation that influenced it.",
    "parameters": [
      {
        "name": "recommendation",
        "type": "Union[Recommendations, str]",
        "required": true,
        "description": "Request ID of the recommendation."
      },
      {
        "name": "item",
        "type": "str",
        "required": true,
        "description": "Purchased product external ID."
      },
      {
        "name": "value",
        "type": "float",
        "required": false,
        "default": "0.0",
        "description": "Monetary value of the conversion in store currency."
      }
    ],
    "returns": "FeedbackReceipt",
    "raises": [
      "AuthenticationError",
      "NotFoundError"
    ],
    "example": "client.storefront.feedback.conversion(\n    recommendation='5b1f0c9e-...',\n    item='SKU-100',\n    value=49.90\n)"
  },
  {
    "name": "events.create",
    "namespace": "client.storefront",
    "signature": "client.storefront.events.create(event_type: str, user_id: str, external_product_id: str, occurred_at: Optional[datetime] = None, event_id: Optional[str] = None, metadata: Optional[dict] = None, rating_value: Optional[float] = None) -> EventReceipt",
    "description": "Records an individual customer interaction event with idempotent deduplication.",
    "parameters": [
      {
        "name": "event_type",
        "type": "str",
        "required": true,
        "description": "One of: 'view', 'click', 'add_to_cart', 'purchase', 'rating', 'add_to_wishlist'."
      },
      {
        "name": "user_id",
        "type": "str",
        "required": true,
        "description": "Shopper external identifier."
      },
      {
        "name": "external_product_id",
        "type": "str",
        "required": true,
        "description": "Catalog product identifier."
      },
      {
        "name": "occurred_at",
        "type": "datetime",
        "required": false,
        "description": "Timestamp when the event occurred in UTC. Defaults to server now."
      },
      {
        "name": "event_id",
        "type": "str",
        "required": false,
        "description": "Unique client-generated idempotency key."
      }
    ],
    "returns": "EventReceipt (accepted: bool, duplicate: bool, event_id: str)",
    "raises": [
      "AuthenticationError",
      "QuotaExceededError",
      "RateLimitError"
    ],
    "example": "client.storefront.events.create(\n    event_type='purchase',\n    user_id='customer-42',\n    external_product_id='SKU-100',\n    metadata={'order_id': 'ORD-991'}\n)"
  },
  {
    "name": "catalog.bulk_upsert",
    "namespace": "client.tenant",
    "signature": "client.tenant.catalog.bulk_upsert(products: Sequence[dict], request_id: Optional[str] = None) -> BulkUpsertResult",
    "description": "Bulk imports up to 1,000 product records per batch. Automatic deduplication and conflict resolution.",
    "parameters": [
      {
        "name": "products",
        "type": "Sequence[dict]",
        "required": true,
        "description": "List of product objects with external_id, title, price, category."
      },
      {
        "name": "request_id",
        "type": "str",
        "required": false,
        "description": "Idempotent batch request identifier."
      }
    ],
    "returns": "BulkUpsertResult (sync_id: str, total_received: int, upserted: int, errors: list)",
    "raises": [
      "AuthenticationError",
      "PayloadTooLargeError",
      "QuotaExceededError"
    ],
    "example": "result = client.tenant.catalog.bulk_upsert([\n    {'external_id': 'SKU-1', 'title': 'Navy Blazer', 'price': '129.00', 'category': 'Suits'},\n    {'external_id': 'SKU-2', 'title': 'Silk Tie', 'price': '34.00', 'category': 'Accessories'}\n])\nprint(f'Upserted {result.upserted} items')"
  },
  {
    "name": "CatalogSync.run",
    "namespace": "graphrec_sdk.ecommerce",
    "signature": "CatalogSync(client: GraphRec, chunk_size: int = 250).run(items: Iterable[dict]) -> SyncSummary",
    "description": "High-level catalog ingestion helper that chunks large inventories to stay under the 16 KiB body limit, retrying transient errors automatically.",
    "parameters": [
      {
        "name": "items",
        "type": "Iterable[dict]",
        "required": true,
        "description": "Complete product inventory iterable."
      },
      {
        "name": "chunk_size",
        "type": "int",
        "required": false,
        "default": "250",
        "description": "Number of items per batch upsert call."
      }
    ],
    "returns": "SyncSummary (total_items: int, batches_sent: int, duration_seconds: float)",
    "raises": [
      "AuthenticationError",
      "RateLimitError"
    ],
    "example": "from graphrec_sdk.ecommerce import CatalogSync\n\nsync = CatalogSync(client)\nsummary = sync.run(products_generator)\nprint(f'Synced {summary.total_items} products')"
  },
  {
    "name": "EventTracker",
    "namespace": "graphrec_sdk.ecommerce",
    "signature": "EventTracker(client: GraphRec, batch_size: int = 100, flush_interval: float = 5.0)",
    "description": "Thread-safe context manager that buffers interaction events in memory and flushes them to the batch endpoint periodically or upon exiting.",
    "parameters": [
      {
        "name": "batch_size",
        "type": "int",
        "required": false,
        "default": "100",
        "description": "Max events to buffer before triggering an automated flush."
      },
      {
        "name": "flush_interval",
        "type": "float",
        "required": false,
        "default": "5.0",
        "description": "Max seconds to wait before flushing pending events."
      }
    ],
    "returns": "Context manager yielding EventTracker instance with .view(), .cart(), .purchase() methods.",
    "raises": [
      "AuthenticationError"
    ],
    "example": "from graphrec_sdk.ecommerce import EventTracker\n\nwith EventTracker(client, batch_size=50) as tracker:\n    tracker.view('cus-99', 'SKU-100')\n    tracker.add_to_cart('cus-99', 'SKU-100', quantity=1)\n    tracker.purchase('cus-99', 'SKU-100', order_id='ORD-1')"
  }
];

export const ERROR_CODES = [
  { code: "malformed_request", status: 400, meaning: "Request validation failed or Content-Type header is not application/json", retryable: false },
  { code: "authentication_failed", status: 401, meaning: "API key or Bearer token is missing, expired, revoked or invalid", retryable: false },
  { code: "insufficient_scope", status: 403, meaning: "Credential is valid but lacks the required permission scope (e.g. catalog:write)", retryable: false },
  { code: "tenant_inactive", status: 403, meaning: "Tenant workspace is suspended or archived. Only status probes are admitted", retryable: false },
  { code: "resource_not_found", status: 404, meaning: "Resource ID does not exist within the caller's tenant boundary", retryable: false },
  { code: "duplicate_resource", status: 409, meaning: "Resource with that ID, version tag or unique constraint already exists", retryable: false },
  { code: "payload_too_large", status: 413, meaning: "Request body exceeded max permitted size (16 KiB default / 50 MiB multipart)", retryable: false },
  { code: "rate_limit_exceeded", status: 429, meaning: "Sliding-window request quota exhausted. Retry-After header indicates wait duration", retryable: true },
  { code: "service_unavailable", status: 503, meaning: "A backend dependency (Postgres or ML model host) is temporarily degraded", retryable: true },
  { code: "recommendation_unavailable", status: 503, meaning: "Model is not serving and fallback_allowed was explicitly set to false", retryable: true },
];

export const PLAN_LIMITS = [
  { dimension: "stored_products", free: "5,000", pro: "50,000", enterprise: "Custom", unit: "SKUs" },
  { dimension: "accepted_events", free: "50,000 / mo", pro: "500,000 / mo", enterprise: "Custom", unit: "events" },
  { dimension: "recommendation_requests", free: "10,000 / mo", pro: "250,000 / mo", enterprise: "Custom", unit: "queries" },
  { dimension: "model_training_jobs", free: "3 / mo", pro: "20 / mo", enterprise: "Unlimited", unit: "runs" },
  { dimension: "api_keys", free: "2 keys", pro: "10 keys", enterprise: "Unlimited", unit: "keys" },
];
