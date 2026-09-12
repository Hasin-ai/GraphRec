from __future__ import annotations

import httpx

#: Default API origin for the Docker Compose stack (``API_PORT`` in ``.env``).
DEFAULT_BASE_URL = "http://localhost:8010"

#: Environment variables read when the matching constructor argument is omitted.
ENV_BASE_URL = "GRAPHREC_BASE_URL"
ENV_API_KEY = "GRAPHREC_API_KEY"
ENV_ACCESS_TOKEN = "GRAPHREC_ACCESS_TOKEN"

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
DEFAULT_MAX_RETRIES = 2

#: Mirrors the server's ``MAX_REQUEST_BODY_BYTES`` default (16 KiB). Bulk helpers
#: split payloads so that no single JSON request exceeds this many bytes.
DEFAULT_MAX_BODY_BYTES = 16_384

#: Upper bound on items per bulk request, independent of the byte budget.
DEFAULT_MAX_BATCH_ITEMS = 500

#: Longest server-suggested ``Retry-After`` the SDK will sleep through automatically.
MAX_RETRY_AFTER_SECONDS = 60.0

INITIAL_RETRY_DELAY = 0.5
MAX_RETRY_DELAY = 8.0

#: Refresh a password-based access token this many seconds before it expires.
TOKEN_EXPIRY_SKEW_SECONDS = 30

API_KEY_PREFIX = "gr_live_"

HEADER_CORRELATION_ID = "X-Correlation-ID"
HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"
